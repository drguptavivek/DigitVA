/**
 * The offline_coding store (Collect Plus offline coding, phase 1) against a real SQLite engine (Node's
 * built-in node:sqlite), wrapped in the same async surface expo-sqlite exposes.
 */
import { DatabaseSync } from "node:sqlite";

import {
  deleteOfflineCoding,
  getOfflineCoding,
  getOfflineCodingCase,
  listOfflineCodingCases,
  migrate,
  saveOfflineCoding,
  type Db,
  type OfflineCodingRow
} from "../src/drafts";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) =>
      db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) =>
      (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close()
  };
}

const CERTIFICATE = JSON.stringify({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "AMI", Code: "BA41.Z" }] }] });
const RESULT = JSON.stringify({ status: "completed", result: { code: "BA41.Z", reject: false } });
const CODEDIT = JSON.stringify({ status: "completed", result: { report: "ok", issueIds: [] } });

function codingRow(overrides: Partial<OfflineCodingRow> = {}): OfflineCodingRow {
  return {
    client_draft_id: "draft-1",
    certificate: CERTIFICATE,
    result: RESULT,
    codedit_result: CODEDIT,
    process_token: "local-abc",
    certificate_digest: "cert-digest",
    result_digest: "result-digest",
    ucod_code: "BA41.Z",
    ucod_uri: "http://id.who.int/icd/entity/1",
    status: "coded",
    coder_profile_updated_at: "2026-10-26T09:00:00.000+05:30",
    provenance: null,
    device_uuid: "device-uuid-1",
    answers_sha256: "c".repeat(64),
    created_at: "2026-10-26T09:00:00.000+05:30",
    updated_at: "2026-10-26T09:00:00.000+05:30",
    ...overrides,
  };
}

/** A completed-but-unsent draft: the only kind the offline coding list may offer. */
function insertDraft(db: Db, id: string, envelope: Record<string, unknown> = {}, columns: Record<string, string | null> = {}, updatedAt = "2026-10-26T10:00:00.000+05:30") {
  db.runAsync(
    "INSERT INTO drafts (id, site_id, completed, updated_at, envelope, org_unit_id, upload_issue, server_draft_id) VALUES (?, ?, 1, ?, ?, ?, ?, ?)",
    [
      id,
      "site-1",
      updatedAt,
      JSON.stringify({ completedAt: "2026-10-26T09:30:00.000+05:30", startedAt: "2026-10-26T09:00:00.000+05:30", ...envelope }),
      columns.org_unit_id ?? "OU-42",
      columns.upload_issue ?? null,
      columns.server_draft_id ?? null,
    ],
  );
}

describe("offline_coding migration", () => {
  it("creates the table with every contract column", async () => {
    const db = memoryDb();
    await migrate(db);
    const columns = await db.getAllAsync<{ name: string }>("PRAGMA table_info(offline_coding)", []);
    expect(columns.map((column) => column.name)).toEqual([
      "id", "client_draft_id", "certificate", "result", "codedit_result", "process_token",
      "certificate_digest", "result_digest", "ucod_code", "ucod_uri", "status",
      "coder_profile_updated_at", "device_uuid", "created_at", "updated_at", "provenance", "answers_sha256",
    ]);
  });

  it("adds provenance to a store created before it, keeping its rows", async () => {
    const db = memoryDb();
    await migrate(db);
    await db.execAsync("ALTER TABLE offline_coding DROP COLUMN provenance");
    await db.runAsync(
      "INSERT INTO offline_coding (client_draft_id, certificate, process_token, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
      ["old", "{}", "local-0", "coded", "2026-10-26T09:00:00.000+05:30", "2026-10-26T09:00:00.000+05:30"],
    );
    await migrate(db);
    expect((await getOfflineCoding(db, "old"))?.provenance).toBeNull();
    await saveOfflineCoding(db, codingRow({ provenance: JSON.stringify({ allowability: { rules: "2026-01+abc" } }) }));
    expect((await getOfflineCoding(db, "draft-1"))?.provenance).toBe(JSON.stringify({ allowability: { rules: "2026-01+abc" } }));
  });

  it("rejects a status outside draft/coded/rejected", async () => {
    const db = memoryDb();
    await migrate(db);
    await expect(db.runAsync(
      "INSERT INTO offline_coding (client_draft_id, certificate, process_token, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
      ["draft-x", "{}", "local-1", "bogus", "2026-10-26T09:00:00.000+05:30", "2026-10-26T09:00:00.000+05:30"],
    )).rejects.toThrow();
  });

  it("keeps one row per interview (client_draft_id unique, with an index)", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveOfflineCoding(db, codingRow());
    await expect(db.runAsync(
      "INSERT INTO offline_coding (client_draft_id, certificate, process_token, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
      ["draft-1", "{}", "local-2", "coded", "2026-10-26T09:00:00.000+05:30", "2026-10-26T09:00:00.000+05:30"],
    )).rejects.toThrow();
    const indexes = await db.getAllAsync<{ name: string }>("PRAGMA index_list(offline_coding)", []);
    expect(indexes.map((index) => index.name)).toContain("ix_offline_coding_draft");
  });

  it("migrating twice changes nothing", async () => {
    const db = memoryDb();
    await migrate(db);
    await migrate(db);
    await saveOfflineCoding(db, codingRow());
    expect(await getOfflineCoding(db, "draft-1")).not.toBeNull();
  });
});

describe("offline_coding accessors", () => {
  it("round-trips a row with device and coder-profile provenance", async () => {
    const db = memoryDb();
    await migrate(db);
    const row = codingRow();
    await saveOfflineCoding(db, row);
    expect(await getOfflineCoding(db, "draft-1")).toEqual(row);
    expect(JSON.parse(row.certificate)).toEqual({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "AMI", Code: "BA41.Z" }] }] });
  });

  it("upserts by interview, keeping created_at and refreshing updated_at", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveOfflineCoding(db, codingRow());
    await saveOfflineCoding(db, codingRow({
      status: "rejected",
      updated_at: "2026-10-26T11:00:00.000+05:30",
      ucod_code: null,
      ucod_uri: null,
    }));
    const stored = await getOfflineCoding(db, "draft-1");
    expect(stored?.status).toBe("rejected");
    expect(stored?.created_at).toBe("2026-10-26T09:00:00.000+05:30");
    expect(stored?.updated_at).toBe("2026-10-26T11:00:00.000+05:30");
    expect(stored?.ucod_code).toBeNull();
  });

  it("reads null before a save and deletes after", async () => {
    const db = memoryDb();
    await migrate(db);
    expect(await getOfflineCoding(db, "draft-1")).toBeNull();
    await saveOfflineCoding(db, codingRow());
    await deleteOfflineCoding(db, "draft-1");
    expect(await getOfflineCoding(db, "draft-1")).toBeNull();
  });
});

describe("the offline coding case list", () => {
  it("lists completed-but-unsent interviews newest first, with coding status", async () => {
    const db = memoryDb();
    await migrate(db);
    insertDraft(db, "draft-old", {}, { org_unit_id: "OU-7" });
    insertDraft(db, "draft-new", {}, {}, "2026-10-26T12:00:00.000+05:30");
    await saveOfflineCoding(db, codingRow({ client_draft_id: "draft-new", status: "coded", ucod_code: "BA41.Z" }));
    insertDraft(db, "draft-in-progress", {}, {});
    db.runAsync("UPDATE drafts SET completed = 0 WHERE id = ?", ["draft-in-progress"]);
    insertDraft(db, "draft-refused", {}, { upload_issue: "demo_limit" });
    insertDraft(db, "draft-sent", {}, { server_draft_id: "srv-1" });

    const rows = await listOfflineCodingCases(db);
    expect(rows.map((row) => row.client_draft_id)).toEqual(["draft-new", "draft-old"]);
    expect(rows[0]).toMatchObject({
      client_draft_id: "draft-new",
      org_unit_id: "OU-42",
      completed_at: "2026-10-26T09:30:00.000+05:30",
      offline_status: "coded",
    });
    expect(rows[1]).toMatchObject({ org_unit_id: "OU-7", offline_status: null });
  });

  it("opens one case with its envelope, only while it stays completed and unsent", async () => {
    const db = memoryDb();
    await migrate(db);
    insertDraft(db, "draft-1");
    const opened = await getOfflineCodingCase(db, "draft-1");
    expect(opened).toMatchObject({ client_draft_id: "draft-1", org_unit_id: "OU-42", completed_at: "2026-10-26T09:30:00.000+05:30" });
    expect(JSON.parse(opened!.envelope).completedAt).toBe("2026-10-26T09:30:00.000+05:30");

    db.runAsync("UPDATE drafts SET server_draft_id = ? WHERE id = ?", ["srv-1", "draft-1"]);
    expect(await getOfflineCodingCase(db, "draft-1")).toBeNull();
    db.runAsync("UPDATE drafts SET server_draft_id = NULL, upload_issue = ? WHERE id = ?", ["case_conflict", "draft-1"]);
    expect(await getOfflineCodingCase(db, "draft-1")).toBeNull();
    expect(await getOfflineCodingCase(db, "missing")).toBeNull();
  });
});
