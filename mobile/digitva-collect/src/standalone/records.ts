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
  /** The deceased's name from the answers (Id10017 + Id10018); "" until answered. Display only, never logged. */
  name: string;
  /** The deceased's age in whole years from the answers; null when not answered. */
  age_years: number | null;
  /** The raw Id10019 value ("male", "female", ...); null when not answered. Map it with sexLabel. */
  sex: string | null;
}

/** The answers read for a row's identity, one json_extract each so the list stays a single query. */
interface IdentityColumns {
  given: unknown; surname: unknown; sex: unknown; age_in_years: unknown; age_in_years2: unknown;
}

const text = (value: unknown) => (typeof value === "string" || typeof value === "number" ? String(value).trim() : "");

/** A non-negative whole number of years from an answer, or null. */
function wholeYears(value: unknown): number | null {
  const raw = text(value);
  const years = raw === "" ? NaN : Number(raw);
  return Number.isFinite(years) && years >= 0 ? Math.floor(years) : null;
}

/**
 * The name, age and sex a record's answers give the deceased. Age is the form's own calculation, which it persists:
 * ageInYears (from the dates of birth and death), else ageInYears2 (from the entered age of the current age group).
 * The raw age_adult/age_child_* answers are not read: a hidden answer is kept after the age group changes.
 */
export function deceasedIdentity(c: IdentityColumns): Pick<StandaloneRecord, "name" | "age_years" | "sex"> {
  const name = [text(c.given), text(c.surname)].filter(Boolean).join(" ");
  return { name, age_years: wholeYears(c.age_in_years) ?? wholeYears(c.age_in_years2), sex: text(c.sex) || null };
}

export async function listStandaloneRecords(db: Db, projectId: string): Promise<StandaloneRecord[]> {
  if (!isStandaloneId(projectId)) return [];
  const rows = await db.getAllAsync<Omit<StandaloneRecord, "completed" | "name" | "age_years" | "sex"> & IdentityColumns & { completed: number }>(
    `SELECT d.id, d.completed, d.updated_at,
            json_extract(d.envelope, '$.startedAt') AS started_at,
            json_extract(d.envelope, '$.completedAt') AS completed_at,
            oc.status AS coding_status, d.upload_issue,
            json_extract(m.value, '$.code') AS refusal_code,
            json_extract(d.envelope, '$.data.Id10017') AS given, json_extract(d.envelope, '$.data.Id10018') AS surname,
            json_extract(d.envelope, '$.data.Id10019') AS sex, json_extract(d.envelope, '$.data.ageInYears') AS age_in_years,
            json_extract(d.envelope, '$.data.ageInYears2') AS age_in_years2
     FROM drafts d LEFT JOIN offline_coding oc ON oc.client_draft_id = d.id
     LEFT JOIN meta m ON m.key = 'senderr:' || d.id
     WHERE d.project_id = ? ORDER BY d.updated_at DESC LIMIT ?`,
    [projectId, MAX_RECORDS],
  );
  return rows.map(({ given, surname, sex, age_in_years, age_in_years2, ...row }) => ({
    ...row,
    completed: row.completed === 1,
    ...deceasedIdentity({ given, surname, sex, age_in_years, age_in_years2 }),
  }));
}

/** When the user last backed up (backupAndShare writes it); null until a backup exists. */
export const lastBackupAt = (db: Db) => getMeta<string>(db, LAST_BACKUP_META_KEY).then((v) => v ?? null);
