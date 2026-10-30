/**
 * The offline DORIS editor (Collect Plus): the DorisEditorProps data callbacks DorisPanel-style editors use, backed by
 * the on-device ICD-11 engine instead of the workspace server. The replies are the server's, field for field:
 * terms, codeinfo and selection-check come from the ports in dorisTerminology.ts (icd11_postcoordination.py and the
 * `_codeinfo_item` of doris_clinical.py), the picker's five guidance routes from dorisGuidance.ts (also
 * icd11_postcoordination.py; `createGuidanceRequester` below routes them), process from dorisProcessing.ts
 * (doris_processing.py) over the certificate
 * rules of dorisCertificate.ts, all through the WHO client of whoEngineApi.ts. A refusal is an ApiError with the
 * server's status, code, message and `{schema_version, error: {code, message, fields?}}` body, so the picker and
 * DorisPanel show what they show for the server's. Only the token differs: `local-<uuid>`, because nothing signs
 * offline (the server does not re-run DORIS on offline results). `certificate_digest` is the server's (SHA-256 of
 * the canonical normalised certificate); `result_digest` binds the engine release instead of the WHO image digest.
 *
 * Personal data never reaches the engine: every text and certificate passes piiBoundary.ts first.
 * Engine failures never carry text here: every failure maps to the server's WHO_API_UNAVAILABLE, because engine
 * payloads can hold stack traces or certificate text. Nothing in this module logs.
 */
import { CryptoDigestAlgorithm, digestStringAsync, randomUUID } from "expo-crypto";

import { ApiError } from "../api";
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
import type { OfflineEngine } from "../offlineEngine";
import type { JsonRequester } from "./api";
import type { DorisCodeInfoReply, DorisProcessReply, DorisTermsReply, JsonObject, JsonValue } from "./contracts";
import { DorisCertificateError, type DorisFieldError } from "./dorisCertificate";
import { createGuidance, GUIDANCE_ENDPOINTS, PostcoordinationError, type GuidanceEndpoint, type GuidanceReply } from "./dorisGuidance";
import { DorisRequestError, processCertificate } from "./dorisProcessing";
import { codeinfoItem, searchTerms, validSubtreeUris } from "./dorisTerminology";
import { assertNoPii, assertNoPiiInText, PiiBoundaryError } from "./piiBoundary";
import { createWhoEngineApi, ENGINE_PROVENANCE, WHO_RELEASE, WhoUnavailableError, type WhoEngineApi } from "./whoEngineApi";
import { codePointLength, isRecord } from "./whoText";

/** The WHO data bundle the engine ships pins this release (app/services/who_icd_api.py DEFAULT_ICD11_RELEASE). */
export const OFFLINE_ICD11_RELEASE = WHO_RELEASE;
const DEFAULT_TERM_LIMIT = 20;
const MAX_TERM_LIMIT = 20;
const MIN_QUERY_CHARS = 2;
const MAX_QUERY_CHARS = 80;
const MAX_CODE_CHARS = 128;
const MAX_URI_CHARS = 2048;

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
  /** The picker's guidance routes (postcoordination, options, hierarchy, related, details): `body` is the JSON the route takes. */
  onGuidance: (endpoint: GuidanceEndpoint, body: unknown) => Promise<GuidanceReply>;
  /** The stem that drives the VA cause of an expression: WHO's causing condition for a `/` cluster, else its first stem. */
  primaryStem: (expression: string) => Promise<string>;
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

const PROCESS_STATUSES = ["completed", "rejected", "timeout", "malformed_response", "unavailable"] as const;

/** The server's error reply (`_error` of doris_clinical.py) as the ApiError the online client raises for it. */
function dorisError(status: number, code: string, message: string, fields?: DorisFieldError[], reason?: string): ApiError {
  const error = new ApiError(status, code, undefined, undefined, {
    schema_version: 1,
    error: { code, message, ...(fields ? { fields } : {}), ...(reason ? { reason } : {}) },
  });
  error.message = message;
  return error;
}

const whoUnavailable = () => dorisError(503, "WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.");
/** A refusal for personal data: the server's INVALID_INPUT, naming the path and rule, never the value; `reason` tells it apart. */
const personalData = (error: PiiBoundaryError, message: string, path = error.path) =>
  dorisError(422, "INVALID_INPUT", message, [{ path, message: error.message }], "pii_boundary");

/** Maps what the ports throw onto the server's replies; `pii` builds the refusal for personal data. */
async function guarded<T>(work: () => Promise<T>, pii: (error: PiiBoundaryError) => ApiError): Promise<T> {
  try {
    return await work();
  } catch (error) {
    if (error instanceof WhoUnavailableError) throw whoUnavailable();
    if (error instanceof PiiBoundaryError) throw pii(error);
    throw error;
  }
}

export function createOfflineDorisEditor(engine: OfflineEngine, store: OfflineCodingStore, allowability?: OfflineAllowability): OfflineDorisEditor {
  const who: WhoEngineApi = createWhoEngineApi(engine);
  const guidance = createGuidance(who);
  /** The engine-reported URI per code a selection check confirmed; the save stores it beside the confirmed code. */
  const confirmedUris = new Map<string, string>();

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
      const info = await who.codeinfo(expression).catch((error: unknown) => {
        throw error instanceof WhoUnavailableError ? new Error("icd11_unavailable") : error;
      });
      const valid = info !== null && info.code === expression
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
      const engineBinding = `icd11-engine-${ENGINE_PROVENANCE.icd11_engine}+doris-${ENGINE_PROVENANCE.doris_engine}+rules-${ENGINE_PROVENANCE.doris_rules}`;
      try {
        // Rule 6 first, as vendor/who-icd11-api's normalize_certificate does: nothing personal reaches the engine.
        assertNoPii(certificate, "certificate");
        const result = await processCertificate(
          who,
          { schema_version: 1, client_revision: clientRevision, certificate },
          { digest: sha256Hex, engineBinding },
        );
        return { ...result, process_token: `local-${randomUUID()}` };
      } catch (error) {
        if (error instanceof DorisCertificateError) throw dorisError(422, "INVALID_INPUT", "The DORIS certificate is invalid.", error.fields);
        if (error instanceof DorisRequestError) throw dorisError(422, "INVALID_INPUT", "The DORIS process request is invalid.");
        if (error instanceof PiiBoundaryError) throw personalData(error, "The DORIS certificate is invalid.", "certificate");
        if (error instanceof WhoUnavailableError) throw whoUnavailable();
        throw error;
      }
    },

    async onTerms(query, limit, subtreeUris) {
      const wanted = limit ?? DEFAULT_TERM_LIMIT;
      const length = codePointLength(typeof query === "string" ? query.trim() : "");
      if (
        length < MIN_QUERY_CHARS || length > MAX_QUERY_CHARS
        || !Number.isInteger(wanted) || wanted < 1 || wanted > MAX_TERM_LIMIT
        || !validSubtreeUris(subtreeUris)
      ) {
        throw dorisError(422, "INVALID_INPUT", "The terminology request is invalid.");
      }
      return guarded(async () => {
        assertNoPiiInText(query, "query");
        subtreeUris?.forEach((uri, index) => assertNoPiiInText(uri, `subtree_uris[${index}]`));
        const { items, truncated } = await searchTerms(who, query, { limit: wanted, subtreeUris });
        return { schema_version: 1 as const, items, truncated, next_cursor: null };
      }, (error) => personalData(error, "The terminology request is invalid."));
    },

    async onCodeInfo(requested) {
      const code = typeof requested === "string" ? requested.trim() : "";
      if (!code || codePointLength(code) > MAX_CODE_CHARS) throw dorisError(422, "INVALID_INPUT", "The code request is invalid.");
      return guarded(async () => {
        assertNoPiiInText(code, "code");
        const item = await codeinfoItem(who, code);
        if (!item) throw dorisError(422, "CODE_NOT_FOUND", "Select a valid ICD-11 code.");
        return { schema_version: 1 as const, item };
      }, (error) => personalData(error, "The code request is invalid."));
    },

    async onSelectionCheck(requested, requestedUri) {
      const code = typeof requested === "string" ? requested.trim() : "";
      const uri = typeof requestedUri === "string" ? requestedUri.trim() : "";
      if (!code || codePointLength(code) > MAX_CODE_CHARS || !uri || codePointLength(uri) > MAX_URI_CHARS) {
        throw dorisError(422, "INVALID_INPUT", "The selected ICD-11 code is invalid.");
      }
      return guarded(async () => {
        assertNoPiiInText(code, "code");
        assertNoPiiInText(uri, "uri");
        const item = await codeinfoItem(who, code);
        // The URI must be the one WHO reports for that code: a picker hint that no longer matches (stale draft, re-shipped data) is refused.
        if (!item || item.uri !== uri) throw dorisError(422, "INVALID_SELECTION", "The selected code does not match its WHO URI.");
        confirmedUris.set(item.code, item.uri);
        return { schema_version: 1 as const, item };
      }, (error) => personalData(error, "The selected ICD-11 code is invalid."));
    },

    async onGuidance(endpoint, body) {
      try {
        return await guidance.answer(endpoint, body);
      } catch (error) {
        if (error instanceof PostcoordinationError) throw dorisError(error.status, error.code, error.message);
        // The guidance routes word this differently from the terms routes (_guidance_request in doris_clinical.py).
        if (error instanceof WhoUnavailableError) throw dorisError(503, "WHO_API_UNAVAILABLE", "WHO ICD-11 guidance is unavailable.");
        if (error instanceof PiiBoundaryError) throw personalData(error, "The ICD-11 guidance request is invalid.");
        throw error;
      }
    },

    async primaryStem(requested) {
      const expression = extractIcd11CodeExpression(requested);
      const first = expression ? firstStem(expression) : null;
      if (!expression || !first) throw dorisError(422, "INVALID_INPUT", "The code request is invalid.");
      if (!isCluster(expression)) return first;
      // The expression passed the code grammar above, which cannot carry personal data: no PII check needed.
      try {
        const info = await who.codeinfo(expression);
        if (!info || info.code !== expression) throw dorisError(422, "CODE_NOT_FOUND", "Select a valid ICD-11 code.");
        return icd11PrimaryStem(info, first);
      } catch (error) {
        throw error instanceof WhoUnavailableError ? whoUnavailable() : error;
      }
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
      const judged = codingProvenance
        ? { ...codingProvenance, workflowTimelineV1: savedTimeline, codingTimelineV1: savedTimeline }
        : timeline.length ? { workflowTimelineV1: savedTimeline, codingTimelineV1: savedTimeline } : {};
      // Which engine produced and judged this coding. The server takes it as `pack_versions` (src/sync.ts moves it there).
      const provenance = { ...judged, packVersions: { ...ENGINE_PROVENANCE } };
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
        provenance: JSON.stringify(provenance),
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

const GUIDANCE_PATH = new RegExp(`^/api/v1/doris-clinical/(${GUIDANCE_ENDPOINTS.join("|")})/([^/?#]+)$`);

/**
 * The requester DorisPanel and the picker's guidance calls (workspace/doris/guidance.ts) use offline: a POST to one of
 * the five `/api/v1/doris-clinical/<route>/<va_sid>` guidance routes for the open case is answered by the editor, with
 * the server's reply or ApiError; every other request throws `offline_server_unavailable`, so an offline screen can
 * never half-talk to a server. `allowed` runs first, as for the editor's other data calls.
 */
export function createGuidanceRequester(editor: Pick<OfflineDorisEditor, "onGuidance">, vaSid: string, allowed: () => Promise<void>): JsonRequester {
  return async (path, init) => {
    const match = GUIDANCE_PATH.exec(path);
    if (!match || init?.method !== "POST" || match[2] !== encodeURIComponent(vaSid)) throw new Error("offline_server_unavailable");
    await allowed();
    return editor.onGuidance(match[1] as GuidanceEndpoint, init.json);
  };
}
