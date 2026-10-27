/**
 * Path C encrypted backup and restore (docs/policy/field-data-collection.md, "Export and backup").
 *
 * Mechanism: SQLCipher re-keying. `ATTACH ... KEY <passphrase>` then `sqlcipher_export` writes a copy of the whole
 * store (answers, attachments, coding, consent) into a SQLCipher file keyed by the user's passphrase; SQLCipher's
 * own PBKDF2 and per-page HMAC do the key derivation and the integrity check, natively. A pure-JS KDF would take
 * minutes on Hermes. The live store's key is Keystore-bound, so a plain copy of it is useless elsewhere; this file
 * is not, which is the point. Inside the file a `backup_info` table is the versioned header: format, version, app
 * version, KDF iterations, source project id, time. The passphrase has no recovery.
 *
 * Restore attaches the picked file with the passphrase (a wrong passphrase and a tampered file both fail the first
 * read), then copies rows into the unlocked store in one transaction. Existing ids are kept unless the person
 * confirms overwriting; newer local records need that confirmation. Rows are re-pointed to this account's project.
 * Standalone accounts only.
 */
import type { Db } from "../drafts";
import { setMeta } from "../drafts";
import { runInTransaction } from "../dbTransaction";
import { APP_VERSION } from "../appVersion";
import { LAST_BACKUP_META_KEY } from "./records";
import { isStandaloneId, standaloneProjectId } from "./project";
import { cacheFile, shareAndDelete, sqlitePath } from "./shareFile";
import { removeFile } from "../mediaFiles";

type Bind = Parameters<Db["runAsync"]>[1][number];

export const BACKUP_FORMAT = "digitva-collect-backup";
export const BACKUP_VERSION = 1;
export const MIN_PASSPHRASE_LENGTH = 12;

export type BackupErrorCode = "standalone_only" | "passphrase_short" | "bad_passphrase_or_file" | "unsupported_backup" | "newer_local";
export class BackupError extends Error {
  constructor(readonly code: BackupErrorCode, readonly count = 0) {
    super(code);
  }
}

export const passphraseValid = (passphrase: string) => passphrase.length >= MIN_PASSPHRASE_LENGTH;

/** Tables restored, with the column that ties a row to the account's project. Fixed list: never from the file. */
const RESTORE_TABLES = ["drafts", "attachments", "offline_coding", "consent_records"] as const;
const quote = (name: string) => `"${name.replace(/"/g, '""')}"`;

async function detach(db: Db) {
  try {
    await db.execAsync("DETACH DATABASE bak");
  } catch {
    // Not attached (the ATTACH itself failed).
  }
}

/** Write the keyed backup file into the private cache and return it; the caller shares and deletes it. */
async function writeBackup(db: Db, userId: string, passphrase: string, now: Date) {
  // Not created here: SQLCipher must create the file itself (an empty plain file is not a database).
  const file = cacheFile(`digitva-backup-${now.toISOString().slice(0, 10)}.dvbak`);
  if (file.exists) file.delete();
  try {
    await db.runAsync("ATTACH DATABASE ? AS bak KEY ?", [sqlitePath(file.uri), passphrase]);
    await db.getFirstAsync("SELECT sqlcipher_export('bak')", []);
    const kdf = await db.getFirstAsync<{ cipher_default_kdf_iter: number }>("PRAGMA cipher_default_kdf_iter", []).catch(() => null);
    await db.execAsync("CREATE TABLE bak.backup_info (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL)");
    const info: Record<string, string> = {
      format: BACKUP_FORMAT, version: String(BACKUP_VERSION), app_version: APP_VERSION, created_at: now.toISOString(),
      kdf: "sqlcipher-pbkdf2-hmac-sha512", kdf_iter: String(kdf?.cipher_default_kdf_iter ?? ""), source_project_id: standaloneProjectId(userId),
    };
    for (const [key, value] of Object.entries(info)) await db.runAsync("INSERT INTO bak.backup_info (key, value) VALUES (?, ?)", [key, value]);
  } catch (error) {
    await detach(db);
    removeFile(file.uri);
    throw error;
  }
  await detach(db);
  return file;
}

/**
 * Back up the whole store under `passphrase`, share the file, delete it, and record `standalone:last_backup_at`.
 * The time is written once the share sheet has been shown and returned without error; the app cannot see whether
 * the person actually saved the file.
 */
export async function backupAndShare(db: Db, userId: string, passphrase: string, now = new Date()): Promise<void> {
  if (!isStandaloneId(userId)) throw new BackupError("standalone_only");
  if (!passphraseValid(passphrase)) throw new BackupError("passphrase_short");
  const file = await writeBackup(db, userId, passphrase, now);
  await shareAndDelete(file, "application/octet-stream");
  await setMeta(db, LAST_BACKUP_META_KEY, now.toISOString());
}

export interface RestoreResult { restored: number; skipped: number }

async function commonColumns(db: Db, table: string): Promise<string[]> {
  const main = await db.getAllAsync<{ name: string }>(`PRAGMA main.table_info(${table})`, []);
  const bak = new Set((await db.getAllAsync<{ name: string }>(`PRAGMA bak.table_info(${table})`, [])).map((c) => c.name));
  return main.map((c) => c.name).filter((n) => bak.has(n));
}

/**
 * Restore a picked backup (a cache copy from the document picker, which is deleted afterwards) into the unlocked
 * store of the standalone account `userId`. Throws BackupError: bad_passphrase_or_file (wrong passphrase or
 * damaged file, indistinguishable by design), unsupported_backup, newer_local (`count` local records are newer
 * than the backup's; call again with confirmOverwrite to replace them), standalone_only.
 */
export async function restoreBackup(db: Db, userId: string, fileUri: string, passphrase: string, confirmOverwrite = false): Promise<RestoreResult> {
  if (!isStandaloneId(userId)) throw new BackupError("standalone_only");
  const target = standaloneProjectId(userId);
  try {
    let info: Record<string, string>;
    try {
      await db.runAsync("ATTACH DATABASE ? AS bak KEY ?", [sqlitePath(fileUri), passphrase]);
      info = Object.fromEntries((await db.getAllAsync<{ key: string; value: string }>("SELECT key, value FROM bak.backup_info", [])).map((r) => [r.key, r.value]));
    } catch {
      throw new BackupError("bad_passphrase_or_file");
    }
    if (info.format !== BACKUP_FORMAT || !info.source_project_id) throw new BackupError("bad_passphrase_or_file");
    if (Number(info.version) > BACKUP_VERSION) throw new BackupError("unsupported_backup");
    const source = info.source_project_id;

    const newer = await db.getFirstAsync<{ n: number }>(
      "SELECT COUNT(*) AS n FROM main.drafts m JOIN bak.drafts b ON b.id = m.id WHERE b.project_id = ? AND m.updated_at > b.updated_at",
      [source],
    );
    if (newer && newer.n > 0 && !confirmOverwrite) throw new BackupError("newer_local", newer.n);

    const total = (await db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM bak.drafts WHERE project_id = ?", [source]))?.n ?? 0;
    const fresh = (await db.getFirstAsync<{ n: number }>(
      "SELECT COUNT(*) AS n FROM bak.drafts b WHERE b.project_id = ? AND NOT EXISTS (SELECT 1 FROM main.drafts m WHERE m.id = b.id)", [source],
    ))?.n ?? 0;
    const verb = confirmOverwrite ? "INSERT OR REPLACE" : "INSERT OR IGNORE";
    const owned = "SELECT id FROM bak.drafts WHERE project_id = ?";
    const where: Record<(typeof RESTORE_TABLES)[number], { sql: string; binds: Bind[] }> = {
      drafts: { sql: "project_id = ?", binds: [source] },
      attachments: { sql: `draft_id IN (${owned})`, binds: [source] },
      offline_coding: { sql: `client_draft_id IN (${owned})`, binds: [source] },
      consent_records: { sql: "project_id = ?", binds: [source] },
    };
    await runInTransaction(db, async (tx) => {
      for (const table of RESTORE_TABLES) {
        const cols = (await commonColumns(tx, table)).filter((c) => !(table === "offline_coding" && c === "id"));
        if (cols.length === 0) continue; // a table missing on either side (an older backup)
        const names = cols.map(quote).join(", ");
        const values = cols.map((c) => (c === "project_id" ? "?" : quote(c)));
        const binds: Bind[] = [...cols.filter((c) => c === "project_id").map(() => target), ...where[table].binds];
        await tx.runAsync(`${verb} INTO main.${table} (${names}) SELECT ${values.join(", ")} FROM bak.${table} WHERE ${where[table].sql}`, binds);
      }
    });
    return { restored: confirmOverwrite ? total : fresh, skipped: confirmOverwrite ? 0 : total - fresh };
  } finally {
    await detach(db);
    removeFile(fileUri);
  }
}
