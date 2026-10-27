/**
 * Path C standalone Collect Plus: local account with no network, PIN unlock, the project-less form definition,
 * records marked standalone, the age warning and backup reminder rules, and the consent guard.
 */
import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  randomUUID: () => "11111111-2222-4333-8444-555555555555",
  digestStringAsync: async (_alg: string, value: string) =>
    require("node:crypto").createHash("sha256").update(value).digest("hex"),
  getRandomBytesAsync: async (n: number) => new Uint8Array(require("node:crypto").randomBytes(n)),
}));
jest.mock("expo-sqlite", () => ({
  openDatabaseAsync: async () => {
    let key: string | null = null;
    return {
      execAsync: async (sql: string) => { const m = /^PRAGMA key = '([^']*)';$/.exec(sql); if (m) key = m[1]; },
      runAsync: async () => undefined,
      getAllAsync: async () => [{ name: "completion" }],
      getFirstAsync: async () => {
        const files = (globalThis as unknown as { __files: Map<string, string | null> }).__files;
        if (!files.has("f")) files.set("f", key);
        if (files.get("f") !== key) throw new Error("Error code 26: file is not a database");
        return { n: 0 };
      },
      closeAsync: async () => undefined,
    };
  },
  deleteDatabaseAsync: async () => undefined,
}));
(globalThis as unknown as { __files: Map<string, string | null> }).__files = new Map();
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => true }));
const mockFetch = jest.fn();
(global as unknown as { fetch: unknown }).fetch = mockFetch;

import { Platform } from "react-native";
import { loadAccounts, unlockInterviewer } from "../src/auth";
import { createDraftStore, migrate, type Db } from "../src/drafts";
import { createInterviewerDb, isUnlocked, lockAll } from "../src/interviewerDb";
import { getOfflineProfile } from "../src/offlineProfile";
import { setUpStandaloneAccount } from "../src/standalone/account";
import { backupReminder, isOverAgeLimit } from "../src/standalone/age";
import { BACKUP_REMINDER_DAYS, STANDALONE_AGE_WARNING_DAYS } from "../src/standalone/config";
import { standaloneConsentConfig } from "../src/standalone/consent";
import { isStandaloneId, STANDALONE_SITE_ID, standaloneDefinition, standaloneProject, standaloneProjectId } from "../src/standalone/project";
import { listStandaloneRecords } from "../src/standalone/records";
import { interviewConsentGate } from "../src/consentStore";

const profile = (over: Record<string, unknown> = {}) => ({
  name: " Asha ", country: "India", facility_name: "PHC 1", org_code: "UNIT7", age_years: null, sex: null,
  designation: "", state: "", hiv_mortality: null, malaria_mortality: null, updated_at: "", ...over,
}) as Parameters<typeof setUpStandaloneAccount>[0];

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

beforeEach(() => {
  mockSecure.clear();
  mockFetch.mockReset();
  (Platform as { OS: string }).OS = "android";
});

describe("local standalone account", () => {
  it("is created with no network, tied to the device uuid and the offline profile", async () => {
    const account = await setUpStandaloneAccount(profile());
    expect(account).toMatchObject({ user_id: "standalone-11111111-2222-4333-8444-555555555555", name: "Asha", standalone: true, collection_access: true });
    expect(await loadAccounts()).toEqual([account]);
    expect(await getOfflineProfile()).toMatchObject({ name: "Asha", org_code: "UNIT7" });
    expect(mockFetch).not.toHaveBeenCalled();
    expect(await setUpStandaloneAccount(profile())).toEqual(account); // idempotent
    expect(await loadAccounts()).toHaveLength(1);
  });

  it("is refused without a name or country, and leaves no account", async () => {
    await expect(setUpStandaloneAccount(profile({ name: " " }))).rejects.toThrow("offline_profile_name_required");
    await expect(setUpStandaloneAccount(profile({ country: "" }))).rejects.toThrow("offline_profile_country_required");
    expect(await loadAccounts()).toEqual([]);
  });

  it("is refused off Android", async () => {
    (Platform as { OS: string }).OS = "ios";
    await expect(setUpStandaloneAccount(profile())).rejects.toThrow();
    expect(await loadAccounts()).toEqual([]);
  });

  it("unlocks with its PIN and not with a wrong one, never calling a server", async () => {
    const account = await setUpStandaloneAccount(profile());
    await createInterviewerDb(account.user_id, "246810");
    await lockAll();
    expect(isUnlocked(account.user_id)).toBe(false);
    expect(await unlockInterviewer(account.user_id, "000000")).toMatchObject({ ok: false });
    expect(await unlockInterviewer(account.user_id, "246810")).toEqual({ ok: true });
    expect(isUnlocked(account.user_id)).toBe(true);
    expect(mockFetch).not.toHaveBeenCalled();
  });
});

describe("project-less interview", () => {
  const userId = "standalone-abc";
  const draft = (id: string): WhoVaDraft => ({
    schemaVersion: 1, formVersion: "f1", id, instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1",
    createdAt: "2026-09-30T00:00:00Z", updatedAt: "2026-09-30T00:00:00Z", data: {} as WhoVaDraft["data"],
  });

  it("starts from the bundled instrument with no server project", () => {
    const resolved = standaloneDefinition([]);
    expect(resolved.provenance).toBe("bundled-original");
    expect(resolved.pin).toBeNull();
    expect(resolved.instrument.sections.length).toBeGreaterThan(0);
    const project = standaloneProject(standaloneProjectId(userId));
    expect(project.form_options.enabled_extensions).toEqual([]);
    expect(isStandaloneId(project.project_id)).toBe(true);
  });

  it("marks stored records standalone and lists only them", async () => {
    const db = memoryDb();
    await migrate(db);
    const projectId = standaloneProjectId(userId);
    await createDraftStore(db, { projectId, siteId: STANDALONE_SITE_ID }).save(draft("d1"));
    await createDraftStore(db, { projectId: "42", siteId: "S1" }).save(draft("server-1"));
    const rows = await db.getAllAsync<{ id: string; project_id: string }>("SELECT id, project_id FROM drafts ORDER BY id", []);
    expect(rows.find((r) => r.id === "d1")!.project_id).toBe(projectId);
    const records = await listStandaloneRecords(db, projectId);
    expect(records.map((r) => r.id)).toEqual(["d1"]);
    expect(records[0].completed).toBe(false);
    expect(await listStandaloneRecords(db, "42")).toEqual([]);
  });
});

describe("age warning and backup reminder", () => {
  const now = new Date("2026-11-30T00:00:00Z");
  const daysAgo = (n: number) => new Date(now.getTime() - n * 86_400_000).toISOString();

  it("warns only past the threshold", () => {
    expect(isOverAgeLimit(daysAgo(STANDALONE_AGE_WARNING_DAYS), now)).toBe(false);
    expect(isOverAgeLimit(daysAgo(STANDALONE_AGE_WARNING_DAYS + 1), now)).toBe(true);
    expect(isOverAgeLimit(null, now)).toBe(false);
    expect(isOverAgeLimit("garbage", now)).toBe(false);
  });

  it("reminds every BACKUP_REMINDER_DAYS since the last backup, or since the oldest record when none", () => {
    expect(backupReminder({ lastBackupAt: null, oldestRecordAt: null, recordCount: 0 }, now).due).toBe(false);
    expect(backupReminder({ lastBackupAt: daysAgo(BACKUP_REMINDER_DAYS - 1), oldestRecordAt: daysAgo(40), recordCount: 3 }, now).due).toBe(false);
    expect(backupReminder({ lastBackupAt: daysAgo(BACKUP_REMINDER_DAYS), oldestRecordAt: daysAgo(40), recordCount: 3 }, now)).toEqual({ due: true, days: BACKUP_REMINDER_DAYS });
    expect(backupReminder({ lastBackupAt: null, oldestRecordAt: daysAgo(2), recordCount: 1 }, now)).toEqual({ due: false, days: null });
    expect(backupReminder({ lastBackupAt: null, oldestRecordAt: daysAgo(9), recordCount: 1 }, now)).toEqual({ due: true, days: null });
  });
});

describe("consent guard", () => {
  it("asks with the bundled notice when the language has one", () => {
    const config = standaloneConsentConfig("standalone-abc", "en", { organisation: "PHC 1" });
    expect(config).not.toBeNull();
    expect(interviewConsentGate(config!).state).toBe("ask");
  });

  it("returns null (the form blocks) when the app has no notice in the language", () => {
    expect(standaloneConsentConfig("standalone-abc", "xx")).toBeNull();
  });
});
