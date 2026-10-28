/**
 * The offline DORIS editor (Collect Plus phase 1): the DorisEditorProps data
 * callbacks DorisPanel-style editors use, backed by the on-device ICD-11
 * engine instead of the workspace server. Search and codeinfo mirror the
 * server's mapping of the same WHO engine payloads
 * (desktop/crates/digitva-server/src/icd11.rs, vendor/who-icd11-api); the
 * process reply mirrors the server's process envelope with a `local-` token.
 *
 * Engine failures never carry text here: every failure maps to a short code
 * or an "unavailable" engine entry, because engine payloads can hold stack
 * traces or certificate text. Nothing in this module logs.
 */
import { CryptoDigestAlgorithm, digestStringAsync, randomUUID } from "expo-crypto";

import { localDateTimeWithOffset } from "../client/localDateTime";
import { appendWorkflowEvent, workflowTimeline, type WorkflowTimelineEvent } from "../workflowTimeline";
import {
  ageRestrictionConfirmation,
  causingConditionUnknownError,
  checkAllowability,
  extractIcd11CodeExpression,
  firstStem,
  icd11PrimaryStem,
  INVALID_EXPRESSION_MESSAGE,
  isCluster,
  type AgeRestriction,
  type AllowabilityIndex,
  type CodingContext,
} from "../coding/icd11Allowability";
import type { OfflineCodingRow } from "../drafts";
import type { OfflineEngine, EngineResult } from "../offlineEngine";
import type { DorisCodeInfoReply, DorisProcessEngine, DorisProcessReply, DorisTerm, DorisTermsReply, JsonObject, JsonValue } from "./contracts";

/** The WHO data bundle the engine ships pins this release (vendor/who-icd11-api DEFAULT_ICD11_RELEASE). */
export const OFFLINE_ICD11_RELEASE = "2026-01";
/** Search results are labelled by classification, not release: the picker shows them beside WHO release URIs. */
const TERMS_RELEASE = "ICD-11";
const MAX_TEXT_CHARS = 2000;
const MAX_CODE_CHARS = 128;
const DEFAULT_TERM_LIMIT = 20;
const MAX_TERM_LIMIT = 20;

/** What a created editor persists through; the screen wires it to the drafts.ts accessors. */
export interface OfflineCodingStore {
  save(row: OfflineCodingRow): Promise<void>;
  get(clientDraftId: string): Promise<OfflineCodingRow | null>;
}

/** The DorisEditorProps data callbacks, plus the save that stores a confirmed coding. */
export interface OfflineDorisEditor {
  onProcess: (clientRevision: number, certificate: JsonObject) => Promise<DorisProcessReply>;
  onTerms: (query: string, limit?: number, subtreeUris?: string[]) => Promise<DorisTermsReply>;
  onCodeInfo: (code: string) => Promise<DorisCodeInfoReply>;
  onSelectionCheck: (code: string, uri: string) => Promise<DorisCodeInfoReply>;
  /** Build the offline_coding row for one confirmed save and persist it; status comes from the engine result. */
  save(input: OfflineCodingSaveInput): Promise<OfflineCodingRow>;
}

/**
 * What a local final is judged by: the exported allowability rules and the deceased's age group and sex (from the
 * interview). `confirmedBy` is the account recorded as having confirmed an age restriction.
 */
export interface OfflineAllowability {
  index: AllowabilityIndex;
  context: CodingContext;
  confirmedBy: string;
}

/**
 * A final the allowability rules refuse. "blocked" is final (non-selectable code, sex conflict, bad expression, bad
 * causing-condition flag); "age_confirm" asks the coder to confirm and save again with age_restriction_confirmed.
 * The screen maps it onto the ApiError shapes DorisPanel already handles for the server's 400 and 422.
 */
export class OfflineAllowabilityError extends Error {
  constructor(readonly kind: "blocked" | "age_confirm", message: string, readonly restriction?: AgeRestriction) {
    super(message);
    this.name = "OfflineAllowabilityError";
  }
}

/** A save DorisPanel posted (its saveInitial body) with the process reply it confirms. */
export interface OfflineCodingSaveInput {
  clientDraftId: string;
  body: JsonObject;
  reply: DorisProcessReply | null;
  deviceUuid: string | null;
  coderProfileUpdatedAt: string | null;
  /** The interview's answers hash now (src/sync.ts draftAnswersSha256): the coding is bound to these answers; absent is stale. */
  answersSha256?: string | null;
  workflowTimelineV1?: WorkflowTimelineEvent[];
  codingTimelineV1?: WorkflowTimelineEvent[];
}

async function sha256Hex(text: string): Promise<string> {
  return digestStringAsync(CryptoDigestAlgorithm.SHA256, text);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** First non-empty string field, the server's first_text. */
function firstText(source: Record<string, unknown>, keys: readonly string[]): string {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value !== "") return value;
  }
  return "";
}

function stripMarkup(text: string): string {
  return text.replace(/<[^>]+>/g, "").trim();
}

/** WHO search text: markup stripped, entities decoded, capped; the server's plain(). */
function plain(value: unknown): string {
  if (typeof value !== "string") return "";
  const decoded = stripMarkup(value)
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, "\"")
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&");
  return decoded.trim().slice(0, MAX_TEXT_CHARS);
}

/** WHO postcoordinationAvailability, the server's postcoordination_availability(). */
function postcoordinationAvailability(raw: unknown): { available: boolean; rawAvailability: JsonValue } {
  if (typeof raw === "boolean") return { available: false, rawAvailability: null };
  if (raw === 0) return { available: false, rawAvailability: 0 };
  if (raw === 1 || raw === 2) return { available: true, rawAvailability: raw };
  return { available: false, rawAvailability: null };
}

/** One WHO search entity as a picker term, or null when it does not resolve to a usable code. */
function termFromEntity(entity: unknown): DorisTerm | null {
  if (!isRecord(entity)) return null;
  const code = firstText(entity, ["theCode", "code"]);
  const uri = firstText(entity, ["id", "uri", "@id"]);
  const title = plain(entity.title ?? entity.titleWithoutCodes);
  if (!code || !uri || !title) return null;
  const rawMatching = entity.matchingPVs ?? entity.matchingText;
  const matching = Array.isArray(rawMatching)
    ? rawMatching.filter((part): part is string => typeof part === "string").join(" ")
    : typeof rawMatching === "string" ? rawMatching : "";
  const { available, rawAvailability } = postcoordinationAvailability(entity.postcoordinationAvailability);
  return {
    code,
    title,
    uri,
    release: TERMS_RELEASE,
    matching_text: plain(matching) || title,
    postcoordination: available,
    postcoordination_availability: rawAvailability,
    related_maternal: entity.hasMaternalChapterLink === true,
    related_perinatal: entity.hasPerinatalChapterLink === true,
    has_coding_note: entity.hasCodingNote === true,
  };
}

const PROCESS_STATUSES = ["completed", "rejected", "timeout", "malformed_response", "unavailable"] as const;

/**
 * The engine's doris/codedit envelope ({status, result}), validated. Anything
 * unexpected — including a failed call — reads as "unavailable" with no
 * result, never with the engine's own error text.
 */
function engineEnvelope(result: EngineResult): DorisProcessEngine {
  const unavailable: DorisProcessEngine = { status: "unavailable", result: null };
  if (!result.ok) return unavailable;
  if (!isRecord(result.data)) return unavailable;
  const status = result.data.status;
  if (typeof status !== "string" || !(PROCESS_STATUSES as readonly string[]).includes(status)) return unavailable;
  const engineResult = result.data.result;
  if (engineResult === null) return { status: status as DorisProcessEngine["status"], result: null };
  if (!isRecord(engineResult)) return unavailable;
  return { status: status as DorisProcessEngine["status"], result: engineResult as JsonObject };
}

/** `1B12.2&XA0G74` / `1B12.2/5A13` → tokens and separators, the engine's split_icd11_expression. */
function splitExpression(code: string): { tokens: string[]; separators: string[] } {
  const tokens: string[] = [];
  const separators: string[] = [];
  let rest = code;
  const pattern = /\s*([&/])\s*/;
  for (let match = pattern.exec(rest); match; match = pattern.exec(rest)) {
    tokens.push(rest.slice(0, match.index));
    separators.push(match[1]);
    rest = rest.slice(match.index + match[0].length);
  }
  tokens.push(rest);
  return { tokens, separators };
}

function cleanCode(code: string): string | null {
  const trimmed = code.trim();
  return trimmed && trimmed.length <= MAX_CODE_CHARS ? trimmed : null;
}

export function createOfflineDorisEditor(engine: OfflineEngine, store: OfflineCodingStore, allowability?: OfflineAllowability): OfflineDorisEditor {
  /** The engine-reported URI per code a selection check confirmed; the save stores it beside the confirmed code. */
  const confirmedUris = new Map<string, string>();

  /**
   * The engine-reported URI for a code or expression: the stemId each part
   * resolves to, post-coordinated parts joined the way the engine's
   * expected_expression_uri_with joins them. Null when a part does not resolve.
   */
  const reportedUri = async (code: string): Promise<string | null> => {
    const { tokens, separators } = splitExpression(code);
    const uris: string[] = [];
    for (const token of tokens) {
      const info = await codeinfoItem(token);
      if (!info) return null;
      const stemId = info.stemId;
      uris.push(stemId);
    }
    if (uris.some((uri) => !uri)) return null;
    return uris.length === 1
      ? uris[0]
      : uris.slice(1).reduce((joined, uri, index) => `${joined} ${separators[index]} ${uri}`, uris[0]);
  };

  /** The engine's codeinfo record for one exact token, or null when WHO does not know it. */
  async function codeinfoItem(code: string): Promise<{ stemId: string; title: string } | null> {
    const result = await engine.codeinfo(code);
    if (!result.ok) throw new Error("icd11_unavailable");
    if (!isRecord(result.data)) return null;
    if (result.data.code !== code) return null;
    const stemId = typeof result.data.stemId === "string" ? result.data.stemId : "";
    if (!stemId) return null;
    const title = plain(result.data.title ?? result.data.label);
    if (!title) return null;
    return { stemId, title };
  }

  const codeInfoReply = async (requested: string): Promise<DorisCodeInfoReply> => {
    const code = cleanCode(requested);
    if (!code) throw new Error("icd11_invalid_code");
    const info = await codeinfoItem(code);
    if (!info) throw new Error("icd11_unknown_code");
    const uri = await reportedUri(code);
    if (!uri) throw new Error("icd11_unknown_code");
    return {
      schema_version: 1,
      item: { code, title: info.title, uri, release: OFFLINE_ICD11_RELEASE, postcoordination: false },
    };
  };

  /**
   * The server's final-cause check (validate_icd11_mms_coding_value_for_submission + record_final_cod_flags) before a
   * local final: returns the provenance to store, or throws OfflineAllowabilityError.
   */
  const judgeUnderlyingCause = async (value: string, body: JsonObject): Promise<JsonObject> => {
    if (!allowability) throw new Error("offline_save_invalid");
    const expression = extractIcd11CodeExpression(value);
    const first = expression ? firstStem(expression) : null;
    if (!expression || !first) throw new OfflineAllowabilityError("blocked", "Select a valid ICD-11 code.");
    let primary = first;
    if (isCluster(expression)) {
      // A cluster is judged by WHO's causing condition, which only codeinfo of the whole expression names.
      const result = await engine.codeinfo(expression);
      if (!result.ok) throw new Error("icd11_unavailable");
      const info = result.data;
      const valid = isRecord(info) && info.code === expression
        && (info.stemCode == null ? typeof info.stemId === "string" : info.stemCode === first);
      if (!valid) throw new OfflineAllowabilityError("blocked", INVALID_EXPRESSION_MESSAGE);
      primary = icd11PrimaryStem(info, first);
    }
    const verdict = checkAllowability(allowability.index, primary, allowability.context);
    if (verdict.status === "blocked") throw new OfflineAllowabilityError("blocked", verdict.message);
    const unknownCause = body.causing_condition_unknown === true;
    const unknownError = unknownCause ? causingConditionUnknownError(expression) : null;
    if (unknownError) throw new OfflineAllowabilityError("blocked", unknownError);
    let confirmation: JsonObject | null = null;
    if (verdict.status === "age_confirm") {
      if (body.age_restriction_confirmed !== true) {
        throw new OfflineAllowabilityError("age_confirm", `${verdict.restriction.code} is not selectable for this submission.`, verdict.restriction);
      }
      const dorisResult = isRecord(body.doris_result) && isRecord(body.doris_result.result) ? body.doris_result.result : {};
      confirmation = ageRestrictionConfirmation(verdict.restriction, allowability.confirmedBy, localDateTimeWithOffset(), dorisResult.warning);
    }
    return {
      allowability: { rules: allowability.index.version, release: allowability.index.release },
      antecedent: {
        code: expression,
        primary_stem: primary,
        release: OFFLINE_ICD11_RELEASE,
        ...(unknownCause ? { causing_condition_unknown: true } : {}),
        ...(confirmation ? { age_restriction_confirmation: confirmation } : {}),
      },
    };
  };

  return {
    async onProcess(clientRevision, certificate) {
      const [dorisRun, codeditRun] = await Promise.all([engine.doris(certificate), engine.codedit(certificate)]);
      const doris = engineEnvelope(dorisRun);
      const codedit = engineEnvelope(codeditRun);
      return {
        schema_version: 1,
        client_revision: clientRevision,
        icd_release: OFFLINE_ICD11_RELEASE,
        certificate,
        // Local integrity markers over the JSON strings; unlike the server's digests they never cross-check WHO.
        certificate_digest: await sha256Hex(JSON.stringify(certificate)),
        result_digest: await sha256Hex(JSON.stringify({ doris, codedit })),
        doris,
        codedit,
        process_token: `local-${randomUUID()}`,
      };
    },

    async onTerms(query, limit, subtreeUris) {
      // The engine's search op takes the query only; subtree filters need WHO
      // search options the offline op does not expose, so a scoped search
      // answers the same flat MMS list until the engine grows the option.
      void subtreeUris;
      const clamped = Math.min(Math.max(limit ?? DEFAULT_TERM_LIMIT, 1), MAX_TERM_LIMIT);
      const result = await engine.search(query);
      if (!result.ok) throw new Error("icd11_unavailable");
      const entities = isRecord(result.data) && Array.isArray(result.data.destinationEntities)
        ? result.data.destinationEntities
        : [];
      const terms: DorisTerm[] = [];
      for (const entity of entities) {
        const term = termFromEntity(entity);
        if (term) terms.push(term);
        if (terms.length === clamped) break;
      }
      const chopped = isRecord(result.data) && result.data.resultChopped !== null && result.data.resultChopped !== undefined
        ? result.data.resultChopped !== false
        : false;
      return {
        schema_version: 1,
        items: terms,
        truncated: chopped || entities.length > terms.length,
        next_cursor: null,
      };
    },

    onCodeInfo: codeInfoReply,

    async onSelectionCheck(code, uri) {
      const reply = await codeInfoReply(code);
      // The URI must be the engine-reported one for that code: a picker hint
      // that no longer matches WHO (stale draft, re-shipped data) is refused.
      if (reply.item.uri !== uri) throw new Error("icd11_uri_mismatch");
      confirmedUris.set(reply.item.code, reply.item.uri);
      return reply;
    },

    async save({ clientDraftId, body, reply, deviceUuid, coderProfileUpdatedAt, answersSha256, workflowTimelineV1, codingTimelineV1 }) {
      const draftId = typeof clientDraftId === "string" ? clientDraftId.trim() : "";
      if (!draftId) throw new Error("offline_save_invalid");
      const certificate = isRecord(body.doris_certificate) ? JSON.stringify(body.doris_certificate) : null;
      const result = engineSavedEnvelope(body.doris_result);
      const codeditResult = engineSavedEnvelope(body.codedit_result);
      const processToken = typeof body.doris_process_token === "string" && body.doris_process_token
        ? body.doris_process_token
        : reply?.process_token ?? "";
      if (!certificate || !result || !codeditResult || !processToken) throw new Error("offline_save_invalid");
      const ucodCode = typeof body.antecedent_cod === "string" && body.antecedent_cod ? body.antecedent_cod : null;
      const existing = await store.get(draftId);
      const parsedProvenance: unknown = existing?.provenance ? JSON.parse(existing.provenance) : undefined;
      if (existing?.provenance && !isRecord(parsedProvenance)) throw new Error("offline_save_invalid");
      const existingProvenance = isRecord(parsedProvenance) ? parsedProvenance : {};
      const codingEvents = new Set(["coding_opened", "doris_processed", "initial_saved", "final_saved"]);
      const timeline = workflowTimeline([
        ...workflowTimeline(existingProvenance.codingTimelineV1 ?? existingProvenance.workflowTimelineV1),
        ...workflowTimeline(codingTimelineV1 ?? workflowTimelineV1),
      ]).filter((event) => codingEvents.has(event.event));
      const updatedAt = localDateTimeWithOffset();
      const savedTimeline = appendWorkflowEvent(timeline, "initial_saved", updatedAt);
      const codingProvenance = allowability && ucodCode ? await judgeUnderlyingCause(ucodCode, body) : null;
      const provenance = codingProvenance
        ? { ...codingProvenance, workflowTimelineV1: savedTimeline, codingTimelineV1: savedTimeline }
        : timeline.length ? { workflowTimelineV1: savedTimeline, codingTimelineV1: savedTimeline } : null;
      const row: OfflineCodingRow = {
        client_draft_id: draftId,
        certificate,
        result: JSON.stringify(result),
        codedit_result: JSON.stringify(codeditResult),
        process_token: processToken,
        certificate_digest: typeof reply?.certificate_digest === "string" ? reply.certificate_digest : null,
        result_digest: typeof reply?.result_digest === "string" ? reply.result_digest : null,
        ucod_code: ucodCode,
        ucod_uri: ucodCode ? confirmedUris.get(ucodCode) ?? null : null,
        // coded only when the engine completed; a rejected certificate stays rejected; no engine verdict stays draft.
        status: result.status === "rejected" ? "rejected" : result.status === "completed" ? "coded" : "draft",
        coder_profile_updated_at: coderProfileUpdatedAt,
        device_uuid: deviceUuid,
        provenance: provenance ? JSON.stringify(provenance) : null,
        answers_sha256: answersSha256 ?? null,
        created_at: existing?.created_at ?? localDateTimeWithOffset(),
        updated_at: updatedAt,
      };
      await store.save(row);
      return row;
    },
  };
}

/** The {status, result} bundle DorisPanel saves, or null when it is not the shape a save must carry. */
function engineSavedEnvelope(value: unknown): { status: string; result: JsonObject | null } | null {
  if (!isRecord(value)) return null;
  if (typeof value.status !== "string" || !(PROCESS_STATUSES as readonly string[]).includes(value.status)) return null;
  if (value.result === null) return { status: value.status, result: null };
  if (!isRecord(value.result)) return null;
  return { status: value.status, result: value.result as JsonObject };
}

/**
 * A certificate seed from the interview's own answers: the non-cause
 * administrative fields the WHO form recorded (docs/policy/doris-cod-workflow.md
 * "Prefill from the interview", direct reads only). Causes and intervals are
 * never prefilled; odd answers are dropped, not repaired. The partial-birth
 * keys are read as the form stored them (first of month/year).
 */
export function certificateSeedFromInterview(data: Record<string, unknown>): { certificate: JsonObject; provenance: JsonObject } {
  const choice = (key: string): string => {
    const value = data[key];
    return typeof value === "string" ? value.trim().toLowerCase() : "";
  };
  const whole = (key: string, min: number, max: number): number | null => {
    const raw = typeof data[key] === "number" ? data[key] : typeof data[key] === "string" && /^-?\d+$/.test(data[key].trim()) ? Number(data[key].trim()) : null;
    return typeof raw === "number" && Number.isInteger(raw) && raw >= min && raw <= max ? raw : null;
  };
  const fullDate = (key: string): string | null => {
    const value = data[key];
    if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value.trim())) return null;
    const [year, month, day] = value.trim().split("-").map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day
      ? value.trim()
      : null;
  };

  const admin: JsonObject = {};
  const provenance: JsonObject = {};
  const put = (field: string, value: JsonValue, sources: string[]) => {
    admin[field] = value;
    provenance[`AdministrativeData.${field}`] = { sources };
  };

  const sex = { male: 1, female: 2, undetermined: 9, other: 9 }[choice("Id10019") as "male" | "female" | "undetermined" | "other"];
  if (sex !== undefined) put("Sex", sex, ["Id10019"]);

  const deathKnown = choice("Id10022");
  const deathDate = deathKnown === "yes"
    ? ["Id10023", "Id10023_a", "Id10023_b"].map(fullDate).find((date) => date !== null) ?? null
    : null;
  if (deathDate) put("DateDeath", deathDate, ["Id10023"]);
  else if (deathKnown === "no" || deathKnown === "ref") {
    const year = data["Id10024"];
    if (typeof year === "string" && /^\d{4}$/.test(year.trim())) put("DateDeath", year.trim(), ["Id10024"]);
  }

  const birthKnown = choice("Id10020");
  const birthDate = birthKnown === "yes" ? fullDate("Id10021") : null;
  if (birthDate) put("DateBirth", birthDate, ["Id10021"]);
  else if (birthKnown === "no" || birthKnown === "ref") {
    const precision = choice("dob_precision");
    const partial = precision === "month_year"
      ? typeof data["dob_month_year"] === "string" && /^\d{4}-\d{2}$/.test(data["dob_month_year"].trim()) ? data["dob_month_year"].trim() : null
      : precision === "year"
        ? typeof data["dob_year"] === "string" && /^\d{4}$/.test(data["dob_year"].trim()) ? data["dob_year"].trim() : null
        : null;
    if (partial) put("DateBirth", partial, [`dob_${precision}`]);
  }

  // The estimated age the interview recorded, as an ISO duration (the editor's EstimatedAge format).
  const group = choice("age_group");
  if (group === "neonate") {
    const days = whole("age_neonate_days", 0, 27);
    const hours = whole("age_neonate_hours", 0, 23);
    if (days === 0 && hours !== null) put("EstimatedAge", `PT${hours}H`, ["age_neonate_hours"]);
    else if (days !== null) put("EstimatedAge", `P${days}D`, ["age_neonate_days"]);
  } else if (group === "child") {
    const unit = choice("age_child_unit");
    const designator = { days: "D", months: "M", years: "Y" }[unit as "days" | "months" | "years"];
    if (designator) {
      const value = whole(`age_child_${unit}`, 1, 999);
      if (value !== null) put("EstimatedAge", `P${value}${designator}`, [`age_child_${unit}`]);
    }
  } else if (group === "adult") {
    const years = whole("age_adult", 1, 150);
    if (years !== null) put("EstimatedAge", `P${years}Y`, ["age_adult"]);
  }

  return {
    certificate: Object.keys(admin).length ? { ICDVersion: "ICD11", AdministrativeData: admin } : { ICDVersion: "ICD11" },
    provenance,
  };
}
