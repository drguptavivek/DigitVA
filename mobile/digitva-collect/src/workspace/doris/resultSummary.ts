import type { JsonObject, JsonValue } from "../contracts";
import { codeditMessages } from "./codeditMessages";
import { describeDorisWarning } from "./dorisWarnings";

/** One engine's part of a processing reply: DORIS or CoDEdit, as the server stores it. */
export interface EngineRun {
  status?: unknown;
  result?: unknown;
}

function object(value: unknown): JsonObject {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as JsonObject : {};
}

function array(value: unknown): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

/** Lines of a report, trimmed, blank ones dropped (as doris_result_summary.js lines()). */
function lines(value: unknown): string[] {
  return typeof value === "string" ? value.split("\n").map((line) => line.trim()).filter(Boolean) : [];
}

/**
 * Report text ready to show: CRLF to LF, trailing spaces removed, and a run of two or more blank lines collapsed
 * to one. "" when there is no text, so the caller can skip an empty box.
 */
export function collapseBlankLines(value: unknown): string {
  if (typeof value !== "string") return "";
  return value.replace(/\r\n?/g, "\n").replace(/[ \t]+$/gm, "").replace(/\n{3,}/g, "\n\n").trim();
}

/** A CoDEdit issue list counts only when it names something: [] and "" mean none. */
function hasIssueIds(value: unknown): boolean {
  return Array.isArray(value) ? value.length > 0 : Boolean(value);
}

// CoDEdit's report is a sentence for front-end rules but a bare key for back-end ones. Its tabular report has one
// row per issue, "n,KEY,BER-CE-9;param0;param1", so a bare key becomes WHO's published sentence with its parameters.
function codeditChecks(result: JsonObject): SummaryCheck[] {
  const rows = lines(result.tabularReport).map((row) => {
    const fields = row.split(";");
    const head = fields[0].split(",");
    return { key: head[1], id: head[2], params: fields.slice(1) };
  });
  const checks = lines(result.report).map((line): string => {
    if (/\s/.test(line)) return line;
    const row = rows.find((candidate) => candidate.key === line);
    const template: string | undefined = row?.id ? codeditMessages[row.id] : undefined;
    if (!row || !template) return `The certificate check (CoDEdit) reported ${line}${row?.id ? ` (${row.id}).` : "."}`;
    return template.replace(/\{(\d+)\}/g, (_match, index: string) => row.params[Number(index)] || "")
      .replace(/ [-–] +[-–] /g, " ").replace(/\(\s*\)/g, "").replace(/\s{2,}/g, " ").trim();
  });
  const texts = checks.length ? checks : [`The certificate check (CoDEdit) reported: ${String(result.issueIds)}`];
  return texts.map((text) => ({ text, original: null }));
}

/** One "Check before you decide" item: its plain text, and DORIS's own text underneath when it was explained. */
export interface SummaryCheck {
  text: string;
  original: string | null;
}

/**
 * The "Check before you decide" items for one DORIS + CoDEdit run, worded as the web summary words them.
 * titleOf(code) gives an ICD-11 title already known for a code named by a known warning, if any.
 */
export function summaryChecks(doris: EngineRun, codedit: EngineRun, titleOf: (code: string) => string | undefined = () => undefined): SummaryCheck[] {
  const dr = object(doris.result);
  const cr = object(codedit.result);
  let checks: SummaryCheck[] = lines(dr.warning).map((warning) => describeDorisWarning(warning, dr.report, titleOf));
  if (codedit.status !== "completed") {
    checks.push({ text: "The certificate check (CoDEdit) did not run.", original: null });
  } else if (hasIssueIds(cr.issueIds) || lines(cr.report).length > 0) {
    checks = checks.concat(codeditChecks(cr));
  }
  return checks;
}

/** Text the coder typed for this code on the certificate, or "" (DORIS can pick a code nobody typed). */
export function certificateTitle(certificate: JsonObject, codes: string[]): string {
  const parts = [...array(certificate.Part1), ...(certificate.Part2 ? [certificate.Part2] : [])];
  for (const part of parts) {
    for (const condition of array(object(part).Conditions)) {
      const entry = object(condition);
      if (typeof entry.Code === "string" && codes.includes(entry.Code)) return typeof entry.Text === "string" ? entry.Text : "";
    }
  }
  return "";
}

/** The codes SmartVA's primary cause maps to in ICD-11: the WHO map joins alternatives with "/" (cod_entry_mode.py). */
export function icd11Alternatives(icd11: unknown): string[] {
  return typeof icd11 === "string" ? icd11.split("/").map((part) => part.trim().toUpperCase()).filter(Boolean) : [];
}
