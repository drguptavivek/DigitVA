import type { Db } from "../drafts";
import type { SmartVaReference } from "./contracts";
import descriptions from "./symptom-descriptions.json";

const controlledSymptoms = new Set(descriptions);

export type LocalSmartVaErrorCode =
  | "unavailable"
  | "init_failed"
  | "engine_error"
  | "native_error"
  | "input_invalid"
  | "answers_changed"
  | "options_unavailable";

export interface LocalSmartVaRow {
  draft_id: string;
  status: "ready" | "error";
  result_json: string | null;
  error_code: LocalSmartVaErrorCode | null;
  answers_sha256: string;
  options_digest: string;
  engine_version: string | null;
  created_at: string;
  updated_at: string;
}

/** A cached advisory result is valid only for the current interview answers and frozen options. */
export function isLocalSmartVaCurrent(
  row: LocalSmartVaRow | null | undefined,
  answersSha: string | null | undefined,
  optionsDigest: string | null | undefined,
  engineVersion: string | null | undefined,
): row is LocalSmartVaRow {
  return !!row && !!answersSha && !!optionsDigest && !!engineVersion && row.engine_version === engineVersion &&
    row.answers_sha256.toLowerCase() === answersSha.toLowerCase() &&
    row.options_digest === optionsDigest;
}

const ERROR_CODES = new Set<LocalSmartVaErrorCode>([
  "unavailable", "init_failed", "engine_error", "native_error", "input_invalid", "answers_changed", "options_unavailable",
]);

function validTimestamp(value: string): boolean {
  return Number.isFinite(Date.parse(value));
}

function validProjection(value: unknown): value is SmartVaReference {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const result = value as Partial<SmartVaReference>;
  return (result.age === null || typeof result.age === "string") &&
    (result.gender === null || typeof result.gender === "string") &&
    Array.isArray(result.key_symptoms) && result.key_symptoms.length <= 3 &&
    result.key_symptoms.every((item) => item === null || controlledSymptoms.has(item)) &&
    Array.isArray(result.causes) && result.causes.length === 3 &&
    result.causes.every((cause) => cause && Number.isInteger(cause.rank) && cause.rank >= 1 && cause.rank <= 3 &&
      (cause.cause === null || typeof cause.cause === "string") &&
      (cause.icd10 === null || typeof cause.icd10 === "string") &&
      (cause.likelihood === null || typeof cause.likelihood === "string")) &&
    Array.isArray(result.symptoms) && result.symptoms.length <= 525 && result.symptoms.every((item) => controlledSymptoms.has(item)) &&
    (result.module === null || typeof result.module === "string") &&
    (result.cause34 === null || typeof result.cause34 === "string") &&
    (result.icd10 === null || typeof result.icd10 === "string");
}

/** Return a single validated advisory result; raw engine output and narratives are never stored. */
export async function getLocalSmartVa(db: Db, draftId: string): Promise<LocalSmartVaRow | null> {
  const row = await db.getFirstAsync<LocalSmartVaRow>(
    `SELECT draft_id, status, result_json, error_code, answers_sha256, options_digest, engine_version, created_at, updated_at
     FROM local_smartva WHERE draft_id = ?`,
    [draftId],
  );
  if (!row || !row.draft_id || !row.answers_sha256 || !row.options_digest || !validTimestamp(row.created_at) || !validTimestamp(row.updated_at)) return null;
  if (row.status === "ready") {
    try {
      const result: unknown = row.result_json ? JSON.parse(row.result_json) : null;
      if (!row.engine_version || !validProjection(result)) return null;
    } catch {
      return null;
    }
  } else if (row.status !== "error" || !row.error_code || !ERROR_CODES.has(row.error_code)) {
    return null;
  }
  return row;
}

export async function saveLocalSmartVaResult(db: Db, input: {
  draftId: string;
  result: SmartVaReference;
  answersSha: string;
  optionsDigest: string;
  engineVersion: string;
  at: string;
}): Promise<void> {
  if (!input.draftId || !input.answersSha || !input.optionsDigest || !input.engineVersion || !validTimestamp(input.at) || !validProjection(input.result)) {
    throw new TypeError("SmartVA result metadata is invalid.");
  }
  const resultJson = JSON.stringify(input.result);
  if (resultJson.length > 48_000) throw new TypeError("SmartVA result is too large.");
  await db.runAsync(
    `INSERT INTO local_smartva (draft_id, status, result_json, error_code, answers_sha256, options_digest, engine_version, created_at, updated_at)
     VALUES (?, 'ready', ?, NULL, ?, ?, ?, ?, ?)
     ON CONFLICT(draft_id) DO UPDATE SET status = 'ready', result_json = excluded.result_json, error_code = NULL,
       answers_sha256 = excluded.answers_sha256, options_digest = excluded.options_digest,
       engine_version = excluded.engine_version, updated_at = excluded.updated_at`,
    [input.draftId, resultJson, input.answersSha, input.optionsDigest, input.engineVersion, input.at, input.at],
  );
}

/** Store only a fixed error code, never native exception text, input, or engine output. */
export async function saveLocalSmartVaError(db: Db, input: {
  draftId: string;
  answersSha: string;
  optionsDigest: string;
  code: unknown;
  at: string;
}): Promise<void> {
  if (!input.draftId || !input.answersSha || !input.optionsDigest || !validTimestamp(input.at)) return;
  const code = typeof input.code === "string" && ERROR_CODES.has(input.code as LocalSmartVaErrorCode)
    ? input.code as LocalSmartVaErrorCode
    : "engine_error";
  await db.runAsync(
    `INSERT INTO local_smartva (draft_id, status, result_json, error_code, answers_sha256, options_digest, engine_version, created_at, updated_at)
     VALUES (?, 'error', NULL, ?, ?, ?, NULL, ?, ?)
     ON CONFLICT(draft_id) DO UPDATE SET status = 'error', result_json = NULL, error_code = excluded.error_code,
       answers_sha256 = excluded.answers_sha256, options_digest = excluded.options_digest,
       engine_version = NULL, updated_at = excluded.updated_at`,
    [input.draftId, code, input.answersSha, input.optionsDigest, input.at, input.at],
  );
}

export async function deleteLocalSmartVa(db: Db, draftId: string): Promise<void> {
  await db.runAsync("DELETE FROM local_smartva WHERE draft_id = ?", [draftId]);
}
