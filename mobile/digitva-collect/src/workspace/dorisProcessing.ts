/**
 * Run a validated death certificate through the on-phone DORIS and CoDEdit: a port of app/services/doris_processing.py
 * (`process_certificate`, `_run_engine`, `processing_extras`, `ucod_parts`, `_certificate_titles`) over the WHO client.
 * The reply has the server's shape: the normalised certificate, the `{status, result}` envelope of each engine with
 * the server's key checks and status mapping, the UCOD split into titled parts and the notes about what was left out.
 *
 * Deliberate differences from the server: (1) the engine gives no HTTP timeout, so `timeout` never occurs and a failed
 * run is `unavailable`; (2) nothing is logged; (3) `result_digest` binds the engine release instead of the WHO image
 * digest, and no process token is signed here (the editor adds `local-<uuid>`); (4) a title lookup that fails does not
 * start the server's 60-second cross-request outage memory, only a flag for the one reply.
 */
import type { DorisProcessEngine, JsonObject, UcodPart } from "./contracts";
import { canonicalJson, normalizeCertificate, verifyCertificateCodes, whoSafeCertificate } from "./dorisCertificate";
import { WHO_RELEASE, WhoUnavailableError, type WhoEngineApi } from "./whoEngineApi";
import { codePointLength, isRecord, type JsonRecord } from "./whoText";

const DORIS_KEYS = ["code", "stemCode", "uri", "stemURI", "report", "tabularReport", "reject", "error", "warning"];
const CODEDIT_KEYS = ["report", "tabularReport", "issueIds"];
const MAX_TITLE_EXPRESSION = 256; // icd11_titles._MAX_CODE_LENGTH
// A DORIS uri joins the parts' URIs with "/" or "&", which also occur inside a URI.
const URI_SPLIT = /\s*[/&]\s*(?=https?:\/\/)/;
const EXPRESSION_PARTS = /\s*([&/])\s*/;
const OMITTED_LABEL: Record<string, string> = { "AdministrativeData.DateBirth": "birth", "AdministrativeData.DateDeath": "death" };

/** The server's ValueError for a process request that is not shaped as the contract says. */
export class DorisRequestError extends Error {
  constructor() {
    super("The DORIS process request is invalid.");
    this.name = "DorisRequestError";
  }
}

export interface ProcessResult {
  schema_version: 1;
  client_revision: number;
  icd_release: string;
  certificate: JsonObject;
  certificate_digest: string;
  result_digest: string;
  doris: DorisProcessEngine;
  codedit: DorisProcessEngine;
  who_notes: string[];
  ucod_parts: UcodPart[];
}

/** `_run_engine`: one engine's answer as a `{status, result}` envelope. Never throws. */
export async function runEngine(who: WhoEngineApi, name: "doris" | "codedit", certificate: JsonRecord): Promise<DorisProcessEngine> {
  const outcome = await who.runProcessor(name, certificate);
  if (outcome.kind === "unavailable") return { status: "unavailable", result: null };
  if (outcome.kind === "malformed") return { status: "malformed_response", result: null };
  const result = outcome.data;
  const keys = name === "doris" ? DORIS_KEYS : CODEDIT_KEYS;
  if (!isRecord(result) || !keys.every((key) => key in result)) return { status: "malformed_response", result: null };
  if (name === "doris" && typeof result.reject !== "boolean") return { status: "malformed_response", result: null };
  const rejected = name === "doris" && result.reject === true;
  return { status: rejected ? "rejected" : "completed", result: result as JsonObject };
}

/** Code -> the text the certifier typed, for every coded condition on the certificate. */
function certificateTitles(certificate: JsonRecord): Map<string, string> {
  const parts: unknown[] = Array.isArray(certificate.Part1) ? [...certificate.Part1] : [];
  if (isRecord(certificate.Part2) && Object.keys(certificate.Part2).length > 0) parts.push(certificate.Part2);
  const titles = new Map<string, string>();
  for (const part of parts) {
    const conditions = isRecord(part) && Array.isArray(part.Conditions) ? part.Conditions : [];
    for (const condition of conditions) {
      if (!isRecord(condition)) continue;
      const { Code: code, Text: text } = condition;
      if (typeof code === "string" && code && typeof text === "string" && text.trim() && !titles.has(code)) titles.set(code, text.trim());
    }
  }
  return titles;
}

/**
 * The computed UCOD split into titled codes for the coder; [] when DORIS chose none. "STEM&EXT/OTHER" is the stem
 * (extension codes joined by "&") and the code(s) DORIS postcoordinated to it. Titles come from the certificate
 * first, then WHO; a failed lookup leaves the title empty and never fails the result.
 */
export async function ucodParts(who: WhoEngineApi, dorisResult: JsonRecord | null, certificate: JsonRecord): Promise<UcodPart[]> {
  const code = dorisResult?.code;
  if (typeof code !== "string" || !code.trim()) return [];
  const uri = dorisResult?.uri;
  const uris = typeof uri === "string" ? uri.trim().split(URI_SPLIT) : [];
  const onCertificate = certificateTitles(certificate);
  let down = false; // one failed lookup skips the rest for this reply (icd11_titles: one outage costs one timeout)

  /** icd11_titles.icd11_title: the title of a code or expression, null when any part has none. */
  const whoTitle = async (expression: string): Promise<string | null> => {
    const text = expression.trim();
    if (!text || codePointLength(text) > MAX_TITLE_EXPRESSION || down) return null;
    const tokens = text.split(EXPRESSION_PARTS).filter((part, index) => index % 2 === 0 && part);
    const titles: string[] = [];
    try {
      for (const token of tokens) titles.push(await who.title(token));
    } catch (error) {
      if (!(error instanceof WhoUnavailableError)) throw error;
      down = true;
      return null;
    }
    return titles.length === 0 || titles.some((title) => !title) ? null : titles.join(" + ");
  };

  const parts: UcodPart[] = [];
  for (const [groupIndex, group] of code.split("/").entries()) {
    for (const [tokenIndex, raw] of group.split("&").entries()) {
      const token = raw.trim();
      if (!token) continue;
      const role: UcodPart["role"] = tokenIndex ? "extension" : groupIndex ? "postcoordinated" : "stem";
      let title = onCertificate.get(token);
      if (!title) {
        try {
          title = (await whoTitle(token)) ?? undefined;
        } catch {
          // A title is a courtesy: never fail the DORIS result.
        }
      }
      parts.push({ code: token, title: title || "", role, uri: null });
    }
  }
  if (uris.length === parts.length) parts.forEach((part, index) => { part.uri = uris[index]; });
  return parts;
}

/** The notes and UCOD parts a processing reply shows beside the engine envelopes. */
export async function processingExtras(who: WhoEngineApi, doris: DorisProcessEngine, certificate: JsonRecord): Promise<{ who_notes: string[]; ucod_parts: UcodPart[] }> {
  const [, omitted] = whoSafeCertificate(certificate);
  const notes: string[] = [];
  if (omitted.length > 0) {
    notes.push(`Year-only dates left out of the WHO check: ${omitted.map((path) => OMITTED_LABEL[path]).join(", ")}. Your entries are kept.`);
  }
  if (String(doris.result?.error || "").startsWith("Internal system error")) {
    notes.push(
      "WHO's DORIS failed internally on this certificate. Check the dates, manner of death and external-cause fields for an inconsistency, or choose the cause without DORIS.",
    );
  }
  return { who_notes: notes, ucod_parts: await ucodParts(who, doris.result, certificate) };
}

/**
 * Validate a process payload and return both independent results. Throws DorisRequestError for a payload that is not
 * `{schema_version: 1, client_revision, certificate}`, DorisCertificateError for a certificate WHO would refuse and
 * WhoUnavailableError when the engine cannot answer codeinfo. `digest` hashes text (SHA-256 hex).
 */
export async function processCertificate(
  who: WhoEngineApi,
  payload: unknown,
  { digest, engineBinding }: { digest: (text: string) => Promise<string>; engineBinding: string },
): Promise<ProcessResult> {
  if (!isRecord(payload) || payload.schema_version !== 1) throw new DorisRequestError();
  const keys = Object.keys(payload).sort().join(",");
  if (keys !== "certificate,client_revision,schema_version") throw new DorisRequestError();
  const revision = payload.client_revision;
  if (typeof revision !== "number" || !Number.isInteger(revision) || revision < 0) throw new DorisRequestError();
  const certificate = normalizeCertificate(payload.certificate);
  await verifyCertificateCodes(who, certificate);

  const [whoCertificate] = whoSafeCertificate(certificate);
  const doris = await runEngine(who, "doris", whoCertificate);
  const codedit = await runEngine(who, "codedit", whoCertificate);
  return {
    schema_version: 1,
    client_revision: revision,
    icd_release: WHO_RELEASE,
    certificate: certificate as JsonObject,
    certificate_digest: await digest(canonicalJson(certificate)),
    result_digest: await digest(canonicalJson({ icd_release: WHO_RELEASE, engine: engineBinding, doris, codedit })),
    doris,
    codedit,
    ...(await processingExtras(who, doris, certificate)),
  };
}
