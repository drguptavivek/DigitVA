import { getMeta, getOfflineCodingCase, type Db } from "../drafts";
import { consentForDraft, getConsentConfig, inheritedConsentRefused } from "../consentStore";
import { isRefused } from "../refusalBoundary";
import { cleanSmartVaInput, createSmartVaRequest } from "./input";
import type { OfflineSmartvaEngine } from "./nativeEngine";
import { isSmartVaOptionsSnapshot, type SmartVaOptionsSnapshot } from "./options";
import { projectSmartVaResult } from "./projection";
import { saveLocalSmartVaError, saveLocalSmartVaResult, type LocalSmartVaErrorCode, type LocalSmartVaRow } from "./localStore";
import descriptions from "./symptom-descriptions.json";

const controlledSymptoms = new Set(descriptions);

export class LocalSmartVaError extends Error {
  constructor(readonly code: LocalSmartVaErrorCode | "options_unavailable" | "offline_case_missing" | "icd11_doris_disabled" | "offline_case_access_revoked") {
    super(code);
    this.name = "LocalSmartVaError";
  }
}

function record(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Read the saved completion, consent and frozen settings again at each scoring boundary. */
export async function assertSmartVaEligible(db: Db, draftId: string, options: SmartVaOptionsSnapshot): Promise<string> {
  const row = await db.getFirstAsync<{ project_id: string | null; death_id: string | null; client_death_id: string | null; completion: string | null; envelope: string }>(
    "SELECT project_id, death_id, client_death_id, completion, envelope FROM drafts WHERE id = ?", [draftId],
  );
  const eligible = await getOfflineCodingCase(db, draftId);
  if (!row?.project_id || !eligible || !row.completion) throw new LocalSmartVaError("offline_case_missing");
  const completion: unknown = JSON.parse(row.completion);
  const envelope: unknown = JSON.parse(row.envelope);
  if (!record(completion) || completion.valid !== true || !record(envelope) || !record(envelope.data)) throw new LocalSmartVaError("offline_case_missing");
  const data = envelope.data;
  if (data.Id10013 !== "yes") throw new LocalSmartVaError("offline_case_missing");
  const consent = await consentForDraft(db, { id: draftId, death_id: row.death_id, client_death_id: row.client_death_id });
  const config = await getConsentConfig(db, row.project_id);
  if (await getMeta<boolean>(db, `consent:server-refused:${draftId}`) === true ||
      isRefused(data, consent?.record.envelope.decision) ||
      (consent && !consent.own && await inheritedConsentRefused(db, draftId)) ||
      (consent?.record.envelope.decision !== "granted" && config?.consent_required !== false)) {
    throw new LocalSmartVaError("offline_case_missing");
  }
  const frozen = await getMeta<{ smartva?: unknown }>(db, `draft-config:${draftId}`);
  if (!isSmartVaOptionsSnapshot(frozen?.smartva) || JSON.stringify(frozen.smartva) !== JSON.stringify(options)) throw new LocalSmartVaError("options_unavailable");
  return eligible.envelope;
}

function safeEngineError(value: unknown): LocalSmartVaErrorCode | "icd11_doris_disabled" {
  const code = record(value) && typeof value.error === "string" ? value.error : "";
  if (code === "icd11_doris_disabled") return "icd11_doris_disabled";
  if (code === "unavailable") return "unavailable";
  if (code === "init_failed") return "init_failed";
  if (code === "bad_request") return "input_invalid";
  if (code === "native_error") return "native_error";
  return "engine_error";
}

function safeReference(value: unknown) {
  const projected = projectSmartVaResult(value);
  return {
    ...projected,
    key_symptoms: projected.key_symptoms.map((item) => item && controlledSymptoms.has(item) ? item : null),
    symptoms: projected.symptoms.filter((item) => controlledSymptoms.has(item)).slice(0, 525),
  };
}

/** Score an eligible interview for an automatic or manual request. */
export async function runLocalSmartVa(input: {
  db: Db;
  draftId: string;
  envelope: string;
  options: SmartVaOptionsSnapshot | null;
  sealedFields?: readonly string[];
  answersHash: () => Promise<string | null>;
  engine: OfflineSmartvaEngine;
  assertAllowed: () => Promise<void>;
  now?: () => string;
}): Promise<LocalSmartVaRow> {
  const assertAllowed = async () => {
    try {
      await input.assertAllowed();
    } catch (error) {
      if (error instanceof Error && error.message === "icd11_doris_disabled") throw new LocalSmartVaError("icd11_doris_disabled");
      throw new LocalSmartVaError("offline_case_access_revoked");
    }
  };
  await assertAllowed();
  if (!isSmartVaOptionsSnapshot(input.options)) throw new LocalSmartVaError("options_unavailable");
  const options = input.options;
  await assertSmartVaEligible(input.db, input.draftId, options);
  const envelope = JSON.parse(input.envelope) as unknown;
  if (!record(envelope) || !record(envelope.data)) throw new LocalSmartVaError("offline_case_missing");
  const eligibleCase = await getOfflineCodingCase(input.db, input.draftId);
  if (!eligibleCase) throw new LocalSmartVaError("offline_case_missing");
  const storedEnvelope = JSON.parse(eligibleCase.envelope) as unknown;
  if (!record(storedEnvelope) || !record(storedEnvelope.data) ||
      JSON.stringify(storedEnvelope.data) !== JSON.stringify(envelope.data) ||
      storedEnvelope.instrumentId !== envelope.instrumentId || storedEnvelope.instrumentVersion !== envelope.instrumentVersion) {
    throw new LocalSmartVaError("offline_case_missing");
  }
  const answerSha = await input.answersHash();
  if (!answerSha || !/^[a-f0-9]{64}$/i.test(answerSha)) throw new LocalSmartVaError("offline_case_missing");
  const at = (input.now ?? (() => new Date().toISOString()))();
  let engineVersion: string | undefined;
  try {
    const request = createSmartVaRequest(
      cleanSmartVaInput(envelope.data, input.draftId, input.sealedFields),
      options.options,
    );
    await assertAllowed();
    await assertSmartVaEligible(input.db, input.draftId, options);
    const scored = await input.engine.score(request);
    if (!scored.ok || !scored.text) throw new LocalSmartVaError(safeEngineError(scored));
    engineVersion = scored.version;
    if (!engineVersion) throw new LocalSmartVaError("unavailable");
    let result: ReturnType<typeof safeReference>;
    try {
      result = safeReference(JSON.parse(scored.text));
    } catch {
      throw new LocalSmartVaError("engine_error");
    }
    if (await input.answersHash() !== answerSha) throw new LocalSmartVaError("answers_changed");
    await assertAllowed();
    await assertSmartVaEligible(input.db, input.draftId, options);
    await saveLocalSmartVaResult(input.db, {
      draftId: input.draftId,
      result,
      answersSha: answerSha,
      optionsDigest: options.optionsDigest,
      engineVersion,
      at,
    });
    return {
      draft_id: input.draftId,
      status: "ready",
      result_json: JSON.stringify(result),
      error_code: null,
      answers_sha256: answerSha,
      options_digest: options.optionsDigest,
      engine_version: engineVersion,
      created_at: at,
      updated_at: at,
    };
  } catch (error) {
    if (error instanceof LocalSmartVaError && ["icd11_doris_disabled", "offline_case_access_revoked", "options_unavailable", "offline_case_missing"].includes(error.code)) throw error;
    await assertAllowed();
    await assertSmartVaEligible(input.db, input.draftId, options);
    if (await input.answersHash() !== answerSha) throw new LocalSmartVaError("answers_changed");
    const code = error instanceof LocalSmartVaError ? error.code as LocalSmartVaErrorCode : "input_invalid";
    await saveLocalSmartVaError(input.db, {
      draftId: input.draftId,
      answersSha: answerSha,
      optionsDigest: options.optionsDigest,
      code,
      at: (input.now ?? (() => new Date().toISOString()))(),
    });
    throw new LocalSmartVaError(code);
  }
}
