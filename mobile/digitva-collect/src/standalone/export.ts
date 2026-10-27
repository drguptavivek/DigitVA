/**
 * Path C export of the user's own records as CSV or JSON (docs/policy/field-data-collection.md, "Export and
 * backup"): interview answers, the consent record, the offline coding result with its provenance. Excluded:
 * attachments (backup only), the PIN, keys and the backup passphrase. "Omit identifiers" is on by default and
 * strips the personal-data fields (./pii.ts). The free-text coding certificate is never exported. Standalone accounts only.
 */
import type { Account } from "../auth";
import type { Db } from "../drafts";
import { removeFile } from "../mediaFiles";
import { cacheFile, shareAndDelete } from "./shareFile";
import { PII_FIELD_IDS } from "./pii";
import { isStandaloneId, standaloneProjectId } from "./project";

export type ExportFormat = "csv" | "json";
const PAGE = 200;

/** Export and backup exist only for a standalone account; an enrolled phone is not an archive. */
export const dataActionsAllowed = (account: Pick<Account, "standalone"> | undefined) => account?.standalone === true;

interface DraftRow { id: string; completed: number; updated_at: string; envelope: string }
type Row = Record<string, string | number | null>;

export interface ExportRecord {
  id: string;
  completed: boolean;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  answers: Record<string, unknown>;
  consent: Row[];
  coding: Row | null;
}

const CONSENT_COLUMNS = "client_draft_id, decision, purposes_json, notice_version_id, notice_language, notice_sha256, mode, witness_present, recorded_at";
const CODING_COLUMNS = "client_draft_id, status, ucod_code, ucod_uri, result, provenance, device_uuid, process_token, certificate_digest, result_digest, coder_profile_updated_at, created_at, updated_at";

const marks = (n: number) => Array(n).fill("?").join(",");

async function byDraft(db: Db, sql: string, ids: string[]): Promise<Map<string, Row[]>> {
  const out = new Map<string, Row[]>();
  for (const row of await db.getAllAsync<Row>(sql, ids)) {
    const key = String(row.client_draft_id);
    out.set(key, [...(out.get(key) ?? []), row]);
  }
  return out;
}

/** Read the account's records, 200 at a time by id (keyset), with consent and coding joined per page. */
export async function collectRecords(db: Db, userId: string, omitIdentifiers = true): Promise<ExportRecord[]> {
  if (!isStandaloneId(userId)) throw new Error("export_standalone_only");
  const projectId = standaloneProjectId(userId);
  const records: ExportRecord[] = [];
  let after = "";
  for (;;) {
    const page = await db.getAllAsync<DraftRow>(
      "SELECT id, completed, updated_at, envelope FROM drafts WHERE project_id = ? AND id > ? ORDER BY id LIMIT ?",
      [projectId, after, PAGE],
    );
    if (page.length === 0) break;
    const ids = page.map((r) => r.id);
    const consent = await byDraft(db, `SELECT ${CONSENT_COLUMNS} FROM consent_records WHERE project_id = ? AND client_draft_id IN (${marks(ids.length)}) ORDER BY recorded_at`, [projectId, ...ids]);
    const coding = await byDraft(db, `SELECT ${CODING_COLUMNS} FROM offline_coding WHERE client_draft_id IN (${marks(ids.length)})`, ids);
    for (const row of page) {
      const envelope = JSON.parse(row.envelope) as { startedAt?: string; completedAt?: string; data?: Record<string, unknown> };
      const answers = Object.fromEntries(Object.entries(envelope.data ?? {}).filter(([k]) => !omitIdentifiers || !PII_FIELD_IDS.has(k)));
      const code = coding.get(row.id)?.[0] ?? null;
      records.push({
        id: row.id,
        completed: row.completed === 1,
        started_at: envelope.startedAt ?? null,
        completed_at: envelope.completedAt ?? null,
        updated_at: row.updated_at,
        answers,
        consent: consent.get(row.id) ?? [],
        coding: code,
      });
    }
    after = ids[ids.length - 1];
  }
  return records;
}

/** A cell the spreadsheet cannot run as a formula, quoted when it needs it. */
function csvCell(value: unknown): string {
  let text = value === null || value === undefined ? "" : typeof value === "object" ? JSON.stringify(value) : String(value);
  // A leading = + @ tab CR or - starts a formula; only a plain number may begin with "-".
  if (/^[=+@\t\r-]/.test(text) && !/^-\d+(\.\d+)?$/.test(text)) text = `'${text}`;
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function toCsv(records: ExportRecord[]): string {
  const answerKeys = [...new Set(records.flatMap((r) => Object.keys(r.answers)))].sort();
  const head = ["id", "completed", "started_at", "completed_at", "updated_at", "consent_decision", "consent_notice_version_id", "consent_notice_sha256", "consent_mode", "consent_recorded_at", "coding_status", "ucod_code", "coding_device_uuid", "coding_process_token", ...answerKeys.map((k) => `a_${k}`)].map(csvCell);
  const lines = records.map((r) => {
    const consent = r.consent[r.consent.length - 1];
    return [
      r.id, r.completed, r.started_at, r.completed_at, r.updated_at,
      consent?.decision, consent?.notice_version_id, consent?.notice_sha256, consent?.mode, consent?.recorded_at,
      r.coding?.status, r.coding?.ucod_code, r.coding?.device_uuid, r.coding?.process_token,
      ...answerKeys.map((k) => r.answers[k]),
    ].map(csvCell).join(",");
  });
  return [head.join(","), ...lines].join("\r\n") + "\r\n";
}

export function buildExport(records: ExportRecord[], format: ExportFormat, omitIdentifiers: boolean, now = new Date()) {
  const stamp = now.toISOString().slice(0, 10);
  if (format === "csv") return { name: `digitva-records-${stamp}.csv`, mime: "text/csv", text: toCsv(records) };
  const text = JSON.stringify({ format: "digitva-collect-export", version: 1, exported_at: now.toISOString(), identifiers_omitted: omitIdentifiers, records }, null, 2);
  return { name: `digitva-records-${stamp}.json`, mime: "application/json", text };
}

/** Collect, write to a private cache file, share, delete. Resolves the number of records shared (0: nothing shared). */
export async function exportAndShare(db: Db, userId: string, format: ExportFormat, omitIdentifiers = true, now = new Date()): Promise<number> {
  const records = await collectRecords(db, userId, omitIdentifiers);
  if (records.length === 0) return 0;
  const { name, mime, text } = buildExport(records, format, omitIdentifiers, now);
  // The plaintext file must not outlive a failed create, write or share.
  const file = cacheFile(name);
  try {
    file.create({ overwrite: true });
    file.write(text);
    await shareAndDelete(file, mime);
  } finally {
    removeFile(file.uri);
  }
  return records.length;
}
