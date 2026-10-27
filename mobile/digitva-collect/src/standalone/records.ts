/** Local standalone interviews for the standalone home: bounded, with the offline coding status joined. */
import type { Db } from "../drafts";
import { getMeta } from "../drafts";
import { isStandaloneId } from "./project";

export const LAST_BACKUP_META_KEY = "standalone:last_backup_at";
const MAX_RECORDS = 200;

export interface StandaloneRecord {
  id: string;
  completed: boolean;
  started_at: string | null;
  completed_at: string | null;
  updated_at: string;
  coding_status: string | null;
  /** A held upload (refused standalone push or a 409) and the server's code for it, shown until sent again. */
  upload_issue: string | null;
  refusal_code: string | null;
}

export async function listStandaloneRecords(db: Db, projectId: string): Promise<StandaloneRecord[]> {
  if (!isStandaloneId(projectId)) return [];
  const rows = await db.getAllAsync<Omit<StandaloneRecord, "completed"> & { completed: number }>(
    `SELECT d.id, d.completed, d.updated_at,
            json_extract(d.envelope, '$.startedAt') AS started_at,
            json_extract(d.envelope, '$.completedAt') AS completed_at,
            oc.status AS coding_status, d.upload_issue,
            json_extract(m.value, '$.code') AS refusal_code
     FROM drafts d LEFT JOIN offline_coding oc ON oc.client_draft_id = d.id
     LEFT JOIN meta m ON m.key = 'senderr:' || d.id
     WHERE d.project_id = ? ORDER BY d.updated_at DESC LIMIT ?`,
    [projectId, MAX_RECORDS],
  );
  return rows.map((row) => ({ ...row, completed: row.completed === 1 }));
}

/** When the user last backed up (backupAndShare writes it); null until a backup exists. */
export const lastBackupAt = (db: Db) => getMeta<string>(db, LAST_BACKUP_META_KEY).then((v) => v ?? null);
