/**
 * Path C export and encrypted backup: identifiers omitted by default, share-and-delete from the private cache,
 * backup/restore round trip, wrong passphrase, tampered file, newer local records, enrolled accounts refused.
 * SQLCipher is not available under Node, so the attached-database calls (ATTACH ... KEY, sqlcipher_export) are
 * emulated over node:sqlite with a key-and-content registry; the real SQLCipher behaviour is a device check.
 */
import { DatabaseSync } from "node:sqlite";
import * as nodeCrypto from "node:crypto";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";

const mockDir = fs.mkdtempSync(path.join(os.tmpdir(), "dvbak-"));
const mockShared: Array<{ name: string; mime: string; bytes: Buffer; existedDuringShare: boolean }> = [];
let mockFailWrite = false;
let mockOnShare: ((bytes: Buffer) => void) | undefined;

jest.mock("expo-file-system", () => {
  const nodeFs = require("node:fs");
  const nodePath = require("node:path");
  class File {
    uri: string;
    constructor(parent: string | { uri: string }, name?: string) {
      const base = typeof parent === "string" ? parent : parent.uri;
      this.uri = name ? base + name : base;
    }
    get path() { return decodeURIComponent(this.uri.replace(/^file:\/\//, "")); }
    get name() { return nodePath.basename(this.path); }
    get exists() { return nodeFs.existsSync(this.path); }
    get contentUri() { return this.uri; }
    create() { nodeFs.writeFileSync(this.path, ""); }
    write(content: string | Uint8Array) { if (mockFailWrite) { nodeFs.writeFileSync(this.path, "partial"); throw new Error("disk full"); } nodeFs.writeFileSync(this.path, content); }
    delete() { nodeFs.rmSync(this.path); }
  }
  return { File, Paths: { get cache() { return { uri: `file://${mockDir}/` }; } }, Directory: class {
    list() { return nodeFs.readdirSync(mockDir).map((n: string) => new File(`file://${mockDir}/`, n)); }
  } };
});
jest.mock("expo-intent-launcher", () => ({
  startActivityAsync: jest.fn(async (_action: string, params: { type: string; extra: Record<string, string> }) => {
    const fs = require("node:fs");
    const path = require("node:path");
    const file = params.extra["android.intent.extra.STREAM"].replace(/^file:\/\//, "");
    const bytes = fs.readFileSync(file);
    mockShared.push({ name: path.basename(file), mime: params.type, bytes, existedDuringShare: true });
    mockOnShare?.(bytes);
  }),
}));
// iOS shares through expo-sharing (src/standalone/shareFile.ts); the same capture runs so both paths see the bytes.
const mockShareAsync = jest.fn(async (uri: string, options: { mimeType: string; UTI?: string; dialogTitle?: string }) => {
  const fs = require("node:fs");
  const path = require("node:path");
  const file = uri.replace(/^file:\/\//, "");
  const bytes = fs.readFileSync(file);
  mockShared.push({ name: path.basename(file), mime: options.mimeType, bytes, existedDuringShare: true });
  mockOnShare?.(bytes);
});
jest.mock("expo-sharing", () => ({ shareAsync: (...args: unknown[]) => (mockShareAsync as (...a: unknown[]) => Promise<void>)(...args) }));
jest.mock("expo-document-picker", () => ({}));
jest.mock("../src/ConfirmDialog", () => ({}));

import { backupAndShare, BackupError, MIN_PASSPHRASE_LENGTH, passphraseValid, restoreBackup } from "../src/standalone/backup";
import { initConsentTables, type ConsentRecordEnvelope } from "../src/consent";
import { saveDraftConsent, type StoredConsent } from "../src/consentStore";
import { getStandaloneConsent, saveStandaloneConsent } from "../src/standaloneConsentStore";
import { migrate, getMeta, type Db } from "../src/drafts";
import { backupReminder } from "../src/standalone/age";
import { buildExport, collectRecords, dataActionsAllowed, exportAndShare, toCsv } from "../src/standalone/export";
import { sweepExportLeftovers } from "../src/standalone/shareFile";
import { LAST_BACKUP_META_KEY, lastBackupAt } from "../src/standalone/records";

import { Platform } from "react-native";
import * as IntentLauncher from "expo-intent-launcher";

// jest-expo runs as iOS; these cases are the Android intent path unless a test switches to iOS.
const setOs = (os: "android" | "ios") => Object.defineProperty(Platform, "OS", { value: os, configurable: true });
const realOs = Platform.OS;
beforeEach(() => setOs("android"));
afterAll(() => setOs(realOs as "android" | "ios"));

const sha = (b: Buffer) => nodeCrypto.createHash("sha256").update(b).digest("hex");
const known = new Map<string, string>(); // content hash -> key (what SQLCipher's page HMAC enforces)

/** node:sqlite with SQLCipher's ATTACH ... KEY and sqlcipher_export emulated. */
function cipherDb(): Db {
  const db = new DatabaseSync(":memory:");
  const pending = new Map<string, string>();
  return {
    execAsync: async (sql) => {
      if (sql.startsWith("DETACH DATABASE bak")) {
        db.exec(sql);
        for (const [file, key] of pending) known.set(sha(fs.readFileSync(file)), key);
        pending.clear();
        return;
      }
      db.exec(sql);
    },
    runAsync: async (sql, params) => {
      if (sql.startsWith("ATTACH DATABASE ? AS bak KEY ?")) {
        const [file, key] = params as string[];
        if (fs.existsSync(file) && fs.statSync(file).size > 0) {
          if (known.get(sha(fs.readFileSync(file))) !== key) throw new Error("file is not a database");
        } else {
          pending.set(file, key);
        }
        db.exec(`ATTACH DATABASE '${file.replace(/'/g, "''")}' AS bak`);
        return undefined;
      }
      return db.prepare(sql).run(...(params as never[]));
    },
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null | Uint8Array>) => db.prepare(sql).all(...(params as never[])) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null | Uint8Array>) => {
      if (sql.startsWith("SELECT sqlcipher_export")) {
        const tables = db.prepare("SELECT name FROM main.sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").all() as Array<{ name: string }>;
        for (const { name } of tables) db.exec(`CREATE TABLE bak."${name}" AS SELECT * FROM main."${name}"`);
        return null;
      }
      if (sql.startsWith("PRAGMA cipher_default_kdf_iter")) return { cipher_default_kdf_iter: 256000 } as T;
      return (db.prepare(sql).get(...(params as never[])) as T | undefined) ?? null;
    },
    closeAsync: async () => db.close(),
  };
}

const USER_A = "standalone-aaaa";
const USER_B = "standalone-bbbb";
const insertDraft = (db: Db, userId: string, id: string, data: Record<string, unknown>, updatedAt = "2026-10-01T00:00:00Z") =>
  db.runAsync(
    "INSERT INTO drafts (id, project_id, site_id, completed, updated_at, envelope) VALUES (?, ?, 'standalone', 1, ?, ?)",
    [id, userId, updatedAt, JSON.stringify({ id, startedAt: "2026-09-30T08:00:00Z", completedAt: "2026-09-30T09:00:00Z", data })],
  );

async function seeded(userId: string): Promise<Db> {
  const db = cipherDb();
  await migrate(db);
  await initConsentTables(db);
  await insertDraft(db, userId, "d1", { Id10017: "Asha", Id10018: "Rao", Id10019: "female", Id10007: "=cmd()" });
  await insertDraft(db, "42", "server-1", { Id10019: "male" });
  const envelope: ConsentRecordEnvelope = {
    client_id: "c1", client_draft_id: "d1", notice_version_id: "v1", notice_language: "en", notice_sha256: "abc", decision: "granted",
    purposes: [], mode: "spoken", witness_present: false, supersedes_client_id: null, recorded_at: "2026-09-30T08:01:00Z",
  };
  // Consent is written the way the app writes it: to `meta`, never to consent_records.
  await saveStandaloneConsent(db, "d1", { envelope, notice_text: "the notice the respondent saw", bundle_version: "b1", bundle_sha256: "bbb" });
  await saveDraftConsent(db, "d1", { envelope, project_id: userId, covered_fields: [], recorded_by: "u" } as StoredConsent);
  await db.runAsync("INSERT INTO meta (key, value) VALUES ('draft-config:d1', '{\"smartva\":1}')", []);
  await db.runAsync(
    `INSERT INTO offline_coding (client_draft_id, certificate, process_token, status, ucod_code, device_uuid, created_at, updated_at)
     VALUES ('d1', 'Asha Rao died of fever', 'tok', 'coded', 'A41', 'dev-1', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z')`, []);
  return db;
}

beforeEach(() => {
  mockShared.length = 0;
  mockOnShare = undefined;
  mockFailWrite = false;
  known.clear();
  for (const f of fs.readdirSync(mockDir)) fs.rmSync(path.join(mockDir, f));
});

describe("export", () => {
  it("omits identifiers by default and keeps them only when the option is off", async () => {
    const db = await seeded(USER_A);
    const [kept] = await collectRecords(db, USER_A, false);
    expect(kept.answers.Id10017).toBe("Asha"); // subject present first
    const [omitted] = await collectRecords(db, USER_A);
    expect(omitted.answers.Id10019).toBe("female");
    expect(omitted.answers).not.toHaveProperty("Id10017");
    expect(omitted.answers).not.toHaveProperty("Id10007");
    expect(omitted.consent[0]).toMatchObject({ decision: "granted", notice_sha256: "abc" });
    expect(omitted.coding).toMatchObject({ status: "coded", ucod_code: "A41", device_uuid: "dev-1" });
    expect(JSON.stringify(omitted)).not.toContain("Asha"); // the certificate is never exported
    const csv = toCsv(await collectRecords(db, USER_A));
    expect(csv.split("\r\n")[0]).toContain("a_Id10019");
    expect(csv.split("\r\n")[0]).not.toContain("a_Id10017");
  });

  it("exports only this account's records and guards spreadsheet formulas", async () => {
    const db = await seeded(USER_A);
    const records = await collectRecords(db, USER_A, false);
    expect(records.map((r) => r.id)).toEqual(["d1"]);
    expect(toCsv(records)).toContain("'=cmd()");
    const json = JSON.parse(buildExport(records, "json", false).text);
    expect(json).toMatchObject({ format: "digitva-collect-export", identifiers_omitted: false });
  });

  it("shares from the private cache and deletes the file afterwards", async () => {
    const db = await seeded(USER_A);
    expect(await exportAndShare(db, USER_A, "csv")).toBe(1);
    expect(mockShared).toHaveLength(1);
    expect(mockShared[0]).toMatchObject({ mime: "text/csv" });
    expect(mockShared[0].name).toMatch(/^digitva-records-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(fs.readdirSync(mockDir)).toEqual([]);
  });

  it("shares through the Android SEND intent on Android, never expo-sharing", async () => {
    const db = await seeded(USER_A);
    mockShareAsync.mockClear();
    expect(await exportAndShare(db, USER_A, "csv")).toBe(1);
    expect(IntentLauncher.startActivityAsync).toHaveBeenCalledWith("android.intent.action.SEND", expect.objectContaining({ type: "text/csv", flags: 1 }));
    expect(mockShareAsync).not.toHaveBeenCalled();
  });

  it("shares through the iOS share sheet with the UTI and deletes the file afterwards", async () => {
    setOs("ios");
    const db = await seeded(USER_A);
    (IntentLauncher.startActivityAsync as jest.Mock).mockClear();
    mockShareAsync.mockClear();
    expect(await exportAndShare(db, USER_A, "csv")).toBe(1);
    expect(mockShareAsync).toHaveBeenCalledTimes(1);
    const [uri, options] = mockShareAsync.mock.calls[0];
    expect(uri).toMatch(/^file:\/\/.*digitva-records-\d{4}-\d{2}-\d{2}\.csv$/);
    expect(options).toEqual({ mimeType: "text/csv", UTI: "public.comma-separated-values-text", dialogTitle: expect.stringMatching(/\.csv$/) });
    expect(IntentLauncher.startActivityAsync).not.toHaveBeenCalled();
    expect(mockShared).toHaveLength(1);
    expect(fs.readdirSync(mockDir)).toEqual([]);
  });

  it("deletes the file on iOS when the share sheet fails", async () => {
    setOs("ios");
    const db = await seeded(USER_A);
    mockOnShare = () => { throw new Error("no target"); };
    await expect(exportAndShare(db, USER_A, "json")).rejects.toThrow("no target");
    expect(mockShared).toHaveLength(1); // the share was reached
    expect(fs.readdirSync(mockDir)).toEqual([]);
  });

  it("prefixes every formula-capable CSV cell, including headers, except plain negative numbers", () => {
    const base = { id: "d", completed: true, started_at: null, completed_at: null, updated_at: "u", consent: [], coding: null };
    const evil = "-2+3+cmd|' /C calc'!A0";
    const csv = toCsv([{ ...base, answers: { a: evil, b: "-12.5", c: "-x", ["x\",y"]: "1" } }]);
    const [head, row] = csv.split("\r\n");
    expect(row).toContain("'-2+3+cmd|' /C calc'!A0");
    expect(row.split(",")).toContain("-12.5");
    expect(row).toContain("'-x");
    expect(head).toContain('"a_x"",y"'); // a header key goes through the same guard and quoting
  });

  it("leaves no plaintext file when the write or the share fails", async () => {
    const db = await seeded(USER_A);
    mockFailWrite = true;
    await expect(exportAndShare(db, USER_A, "csv")).rejects.toThrow("disk full");
    expect(fs.readdirSync(mockDir)).toEqual([]);
    mockFailWrite = false;
    mockOnShare = () => { throw new Error("no target"); };
    await expect(exportAndShare(db, USER_A, "json")).rejects.toThrow();
    expect(fs.readdirSync(mockDir)).toEqual([]);
  });

  it("sweeps stale export and backup files but nothing else", () => {
    for (const n of ["digitva-records-2026-01-01.csv", "digitva-backup-2026-01-01.dvbak", "attachment-1767225600000-a.pdf", "keep.txt"]) fs.writeFileSync(path.join(mockDir, n), "x");
    sweepExportLeftovers();
    expect(fs.readdirSync(mockDir)).toEqual(["keep.txt"]);
  });

  it("refuses an enrolled account and shows no actions for it", async () => {
    const db = await seeded(USER_A);
    await expect(collectRecords(db, "42")).rejects.toThrow("export_standalone_only");
    expect(dataActionsAllowed({ standalone: undefined })).toBe(false);
    expect(dataActionsAllowed({ standalone: false })).toBe(false);
    expect(dataActionsAllowed(undefined)).toBe(false);
    expect(dataActionsAllowed({ standalone: true })).toBe(true);
  });
});

describe("encrypted backup", () => {
  const PASS = "correct horse battery";

  async function backupFile(db: Db): Promise<string> {
    let bytes: Buffer | undefined;
    mockOnShare = (b) => { bytes = b; };
    await backupAndShare(db, USER_A, PASS, new Date("2026-10-20T00:00:00Z"));
    mockOnShare = undefined;
    const picked = path.join(mockDir, "picked.dvbak");
    fs.writeFileSync(picked, bytes!);
    return `file://${picked}`;
  }

  it("enforces the passphrase length and shares nothing when it is short", async () => {
    const db = await seeded(USER_A);
    expect(passphraseValid("x".repeat(MIN_PASSPHRASE_LENGTH - 1))).toBe(false);
    await expect(backupAndShare(db, USER_A, "short")).rejects.toMatchObject({ code: "passphrase_short" });
    await expect(backupAndShare(db, "42", "short")).rejects.toMatchObject({ code: "passphrase_short" });
    expect(mockShared).toHaveLength(0);
  });

  it("keeps the picked file for the confirmed retry and records no backup time when the read-back fails", async () => {
    const source = await seeded(USER_A);
    const uri = await backupFile(source);
    const target = cipherDb();
    await migrate(target);
    await initConsentTables(target);
    await insertDraft(target, USER_B, "d1", { Id10019: "local newer" }, "2026-10-26T00:00:00Z");
    await expect(restoreBackup(target, USER_B, uri, PASS)).rejects.toMatchObject({ code: "newer_local" });
    expect(fs.existsSync(uri.replace("file://", ""))).toBe(true); // kept for the retry
    expect(await restoreBackup(target, USER_B, uri, PASS, true)).toEqual({ restored: 1, skipped: 0 });
    expect(fs.existsSync(uri.replace("file://", ""))).toBe(false); // gone once the retry finished

    const db = await seeded(USER_A);
    const real = db.getFirstAsync;
    db.getFirstAsync = (async (sql: string, params: never) => (sql.includes("bak.backup_info") ? null : real(sql, params))) as Db["getFirstAsync"];
    mockShared.length = 0;
    await expect(backupAndShare(db, USER_A, PASS, new Date("2026-10-21T00:00:00Z"))).rejects.toMatchObject({ code: "backup_unverified" });
    expect(await getMeta<string>(db, LAST_BACKUP_META_KEY)).toBeUndefined();
    expect(mockShared).toHaveLength(0);
    expect(fs.readdirSync(mockDir).filter((n) => n.endsWith(".dvbak"))).toEqual([]);
  });

  it("round-trips onto another standalone account, re-pointing rows, and clears the reminder", async () => {
    const source = await seeded(USER_A);
    const now = new Date("2026-10-27T00:00:00Z");
    const before = backupReminder({ lastBackupAt: await lastBackupAt(source), oldestRecordAt: "2026-09-30T08:00:00Z", recordCount: 1 }, now);
    expect(before.due).toBe(true);

    const uri = await backupFile(source);
    expect(mockShared[0].mime).toBe("application/octet-stream");
    expect(fs.readdirSync(mockDir)).toEqual(["picked.dvbak"]); // the shared copy is gone
    expect(await getMeta<string>(source, LAST_BACKUP_META_KEY)).toBe("2026-10-20T00:00:00.000Z");
    const after = backupReminder({ lastBackupAt: await lastBackupAt(source), oldestRecordAt: "2026-09-30T08:00:00Z", recordCount: 1 }, new Date("2026-10-22T00:00:00Z"));
    expect(after.due).toBe(false);

    const target = cipherDb();
    await migrate(target);
    await initConsentTables(target);
    const result = await restoreBackup(target, USER_B, uri, PASS);
    expect(result).toEqual({ restored: 1, skipped: 0 });
    expect(await target.getAllAsync("SELECT id, project_id FROM drafts", [])).toEqual([{ id: "d1", project_id: USER_B }]);
    expect(await target.getAllAsync("SELECT client_draft_id, ucod_code FROM offline_coding", [])).toEqual([{ client_draft_id: "d1", ucod_code: "A41" }]);
    expect(await getStandaloneConsent(target, "d1")).toMatchObject({ notice_text: "the notice the respondent saw", envelope: { decision: "granted", notice_sha256: "abc" } });
    expect(await getMeta(target, "consent:draft:d1")).toMatchObject({ envelope: { decision: "granted" } });
    expect(await getMeta(target, "draft-config:d1")).toEqual({ smartva: 1 });
    expect(fs.existsSync(uri.replace("file://", ""))).toBe(false); // the picked copy is deleted
  });

  it("fails cleanly on a wrong passphrase and changes nothing", async () => {
    const uri = await backupFile(await seeded(USER_A));
    const target = cipherDb();
    await migrate(target);
    await expect(restoreBackup(target, USER_B, uri, "another passphrase")).rejects.toMatchObject({ code: "bad_passphrase_or_file" });
    expect(await target.getAllAsync("SELECT id FROM drafts", [])).toEqual([]);
    // The file survives a failed attempt only because removeFile is for the picked copy; recreate to prove no stuck attachment.
    const again = await backupFile(await seeded(USER_A));
    await expect(restoreBackup(target, USER_B, again, PASS)).resolves.toMatchObject({ restored: 1 });
  });

  it("fails on a tampered file", async () => {
    const uri = await backupFile(await seeded(USER_A));
    const file = uri.replace("file://", "");
    const bytes = fs.readFileSync(file);
    bytes[bytes.length - 5] ^= 0xff;
    fs.writeFileSync(file, bytes);
    const target = cipherDb();
    await migrate(target);
    await expect(restoreBackup(target, USER_B, uri, PASS)).rejects.toBeInstanceOf(BackupError);
    expect(await target.getAllAsync("SELECT id FROM drafts", [])).toEqual([]);
  });

  it("asks before replacing newer local records and never overwrites without the confirmation", async () => {
    const source = await seeded(USER_A);
    const uri = await backupFile(source);
    const target = cipherDb();
    await migrate(target);
    await initConsentTables(target);
    await insertDraft(target, USER_B, "d1", { Id10019: "local newer" }, "2026-10-26T00:00:00Z");
    await expect(restoreBackup(target, USER_B, uri, PASS)).rejects.toMatchObject({ code: "newer_local", count: 1 });
    expect(JSON.stringify(await target.getAllAsync("SELECT envelope FROM drafts", []))).toContain("local newer");

    const second = await backupFile(source);
    expect(await restoreBackup(target, USER_B, second, PASS, true)).toEqual({ restored: 1, skipped: 0 });
    expect(JSON.stringify(await target.getAllAsync("SELECT envelope FROM drafts", []))).toContain("Asha");
  });

  it("keeps existing older-or-equal local ids and restores only the missing ones", async () => {
    const uri = await backupFile(await seeded(USER_A));
    const target = cipherDb();
    await migrate(target);
    await insertDraft(target, USER_B, "d1", { Id10019: "local" }, "2026-09-01T00:00:00Z");
    expect(await restoreBackup(target, USER_B, uri, PASS)).toEqual({ restored: 0, skipped: 1 });
    expect(JSON.stringify(await target.getAllAsync("SELECT envelope FROM drafts", []))).toContain("local");
  });

  it("refuses a standalone backup on an enrolled account", async () => {
    const uri = await backupFile(await seeded(USER_A));
    const target = cipherDb();
    await migrate(target);
    await expect(restoreBackup(target, "42", uri, PASS)).rejects.toMatchObject({ code: "wrong_account" });
    expect(await target.getAllAsync("SELECT id FROM drafts", [])).toEqual([]);
  });

  describe("enrolled account, unsent work only", () => {
    async function enrolledBackup(db: Db, userId = "42"): Promise<string> {
      let bytes: Buffer | undefined;
      mockOnShare = (b) => { bytes = b; };
      await backupAndShare(db, userId, PASS, new Date("2026-10-20T00:00:00Z"));
      mockOnShare = undefined;
      const picked = path.join(mockDir, `picked-${userId}.dvbak`);
      fs.writeFileSync(picked, bytes!);
      return `file://${picked}`;
    }
    async function enrolledStore(): Promise<Db> {
      const db = await seeded(USER_A);
      await db.runAsync("INSERT INTO cases (death_id, project_id, position, row) VALUES ('c', '42', 0, '{}')", []);
      await db.runAsync("INSERT INTO meta (key, value) VALUES ('secret-token', 'zzz')", []);
      return db;
    }

    it("backs up only drafts, attachments, coding and consent, never cases or meta", async () => {
      const db = await enrolledStore();
      await enrolledBackup(db);
      expect(mockShared).toHaveLength(1);
      const target = cipherDb();
      await migrate(target);
      await initConsentTables(target);
      const result = await restoreBackup(target, "42", `file://${path.join(mockDir, "picked-42.dvbak")}`, PASS);
      expect(result.restored).toBeGreaterThan(0); // subject present before asserting absence
      expect(await target.getAllAsync("SELECT id FROM drafts ORDER BY id", [])).toEqual([{ id: "d1" }, { id: "server-1" }]);
      expect(await target.getAllAsync("SELECT project_id FROM drafts WHERE id = 'server-1'", [])).toEqual([{ project_id: "42" }]); // not re-pointed
      expect(await target.getAllAsync("SELECT key FROM meta WHERE key = 'secret-token'", [])).toEqual([]);
      expect(await getMeta(target, "consent:draft:d1")).toMatchObject({ envelope: { decision: "granted" } }); // consent travels with the unsent draft
      expect(await getStandaloneConsent(target, "d1")).toMatchObject({ notice_text: "the notice the respondent saw" });
      expect(await target.getAllAsync("SELECT death_id FROM cases", [])).toEqual([]);
      expect(await target.getFirstAsync("SELECT value FROM meta WHERE key = ?", [LAST_BACKUP_META_KEY])).toBeNull();
    });

    it("refuses a backup made by another account and changes nothing", async () => {
      const uri = await enrolledBackup(await enrolledStore(), "42");
      const target = cipherDb();
      await migrate(target);
      await expect(restoreBackup(target, "43", uri, PASS)).rejects.toMatchObject({ code: "wrong_account" });
      expect(await target.getAllAsync("SELECT id FROM drafts", [])).toEqual([]);
    });

    it("keeps drafts already on the phone and never overwrites them", async () => {
      const uri = await enrolledBackup(await enrolledStore());
      const target = cipherDb();
      await migrate(target);
      await insertDraft(target, "42", "d1", { Id10019: "local" }, "2026-09-01T00:00:00Z");
      expect(await restoreBackup(target, "42", uri, PASS)).toEqual({ restored: 1, skipped: 1 });
      expect(JSON.stringify(await target.getAllAsync("SELECT envelope FROM drafts WHERE id = 'd1'", []))).toContain("local");
    });

    it("keeps the phone's own consent for a draft the backup also holds", async () => {
      const uri = await enrolledBackup(await enrolledStore());
      const target = cipherDb();
      await migrate(target);
      await initConsentTables(target);
      await insertDraft(target, "42", "d1", { Id10019: "local" }, "2026-09-01T00:00:00Z");
      const local: ConsentRecordEnvelope = {
        client_id: "c-local", client_draft_id: "d1", notice_version_id: "v2", notice_language: "en", notice_sha256: "local", decision: "granted",
        purposes: [], mode: "spoken", witness_present: false, supersedes_client_id: null, recorded_at: "2026-10-05T08:00:00Z",
      };
      await saveStandaloneConsent(target, "d1", { envelope: local, notice_text: "the phone's own notice", bundle_version: "b2", bundle_sha256: "ccc" });
      await saveDraftConsent(target, "d1", { envelope: local, project_id: "42", covered_fields: [], recorded_by: "u" } as StoredConsent);

      expect(await restoreBackup(target, "42", uri, PASS)).toEqual({ restored: 1, skipped: 1 });
      expect(await getStandaloneConsent(target, "d1")).toMatchObject({ notice_text: "the phone's own notice" });
      expect(await getMeta(target, "consent:draft:d1")).toMatchObject({ envelope: { client_id: "c-local" } });
      // The restored draft (server-1) has no consent in the backup; the backup's d1 consent did not leak onto it.
      expect(await getMeta(target, "consent:draft:server-1")).toBeUndefined();
    });
  });
});
