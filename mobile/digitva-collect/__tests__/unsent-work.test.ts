/** The shared unsent count: ready-to-send only, drafts apart, attention items with their last error. Real SQLite as drafts.test.ts. */
import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import { createDraftStore, markCompleted, migrate, type Db } from "../src/drafts";
import { pendingErrors, resetErrorLog } from "../src/errorLog";
import { ApiError } from "../src/api";
import { listDraftNames } from "../src/ui/interviewRows";
import { clearSendError, MAX_ITEMS, noteSendError, summariseWork } from "../src/unsentWork";

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
const draft = (id: string, data: Record<string, unknown> = {}): WhoVaDraft => ({
  schemaVersion: 1, formVersion: "f1", id, instrumentId: "who-va-2022", instrumentVersion: "1", currentSection: "s1",
  createdAt: "2026-09-30T00:00:00Z", updatedAt: "2026-09-30T00:00:00Z", data: data as WhoVaDraft["data"],
});

let db: Db;
const save = async (id: string, completion?: { valid: boolean }, data: Record<string, unknown> = {}) => {
  await createDraftStore(db, { projectId: "P1", siteId: "S1" }).save(draft(id, data));
  if (completion) await markCompleted(db, id, { valid: completion.valid, issues: [] });
};
beforeEach(async () => { db = memoryDb(); await migrate(db); resetErrorLog(); });

it("does not count drafts in progress as unsent; counts them as in progress", async () => {
  await save("d1");
  await save("d2");
  await save("ready", { valid: true });
  expect(await summariseWork(db)).toMatchObject({ unsent: 1, attention: 0, inProgress: 2 });
});

it("counts the four things Send now uploads, and nothing else", async () => {
  await save("done", { valid: true });
  await db.runAsync("INSERT INTO registrations (client_death_id, project_id, site_id, fields, created_at) VALUES (?, ?, ?, ?, ?)", ["reg", "P1", "S1", JSON.stringify({ deceased_name: "Sunita" }), "2026-09-30"]);
  await db.runAsync("INSERT INTO case_actions (client_id, project_id, kind, death_id, body, created_at) VALUES (?, ?, ?, ?, ?, ?)", ["act", "P1", "visit", "C1", "{}", "2026-09-30"]);
  await db.runAsync("INSERT INTO revision_drafts (draft_id, project_id, state, updated_at, row_json) VALUES (?, ?, ?, ?, ?)", ["rv", "P1", "ready", "2026-09-30", JSON.stringify({ va_sid: "VA1", deceased_name: "Mohan" })]);
  await db.runAsync("INSERT INTO revision_drafts (draft_id, project_id, state, updated_at, row_json) VALUES (?, ?, ?, ?, ?)", ["rv2", "P1", "editing", "2026-09-30", "{}"]);
  const work = await summariseWork(db);
  expect(work).toMatchObject({ unsent: 4, attention: 0, inProgress: 1 });
  expect(work.items.map((item) => item.title)).toEqual(expect.arrayContaining(["Sunita", "Mohan"]));
});

it("lists work Send cannot move as attention with its last error, outside the unsent count", async () => {
  await save("invalid", { valid: false }); // completed but not uploadable
  await db.runAsync("INSERT INTO registrations (client_death_id, project_id, site_id, fields, state, created_at) VALUES (?, ?, ?, ?, 'needs_edit', ?)", ["reg", "P1", "S1", "{}", "2026-09-30"]);
  await noteSendError(db, "reg", new ApiError(422, "invalid_registration", undefined, undefined, undefined, "/intake/deaths", "POST"));
  const work = await summariseWork(db);
  expect(work).toMatchObject({ unsent: 0, attention: 2 });
  expect(work.items.find((item) => item.kind === "registration")).toMatchObject({ state: "attention", error: "HTTP 422 invalid_registration POST /intake/deaths" });
  expect(work.items.find((item) => item.kind === "interview")).toMatchObject({ state: "attention", error: "not_ready" });
  expect(pendingErrors().map((e) => e.what)).toContain("send HTTP 422 invalid_registration POST /intake/deaths");
  await clearSendError(db, "reg");
  expect((await summariseWork(db)).items.find((item) => item.kind === "registration")?.error).toBe("needs_edit");
});

it("treats a draft that follows a pending registration as waiting (counted), and one behind a refused registration as attention", async () => {
  await save("after", { valid: true });
  await db.runAsync("UPDATE drafts SET client_death_id = ? WHERE id = ?", ["reg", "after"]);
  await db.runAsync("INSERT INTO registrations (client_death_id, project_id, site_id, fields, created_at) VALUES (?, ?, ?, ?, ?)", ["reg", "P1", "S1", "{}", "2026-09-30"]);
  expect(await summariseWork(db)).toMatchObject({ unsent: 2, attention: 0 });
  await db.runAsync("UPDATE registrations SET state = 'needs_edit'", []);
  expect(await summariseWork(db)).toMatchObject({ unsent: 0, attention: 2 });
});

it("keeps counts exact while capping the item list", async () => {
  for (let i = 0; i < MAX_ITEMS + 5; i += 1) {
    await db.runAsync("INSERT INTO registrations (client_death_id, project_id, site_id, fields, created_at) VALUES (?, ?, ?, ?, ?)", [`r${i}`, "P1", "S1", "{}", "2026-09-30"]);
  }
  const work = await summariseWork(db);
  expect(work.unsent).toBe(MAX_ITEMS + 5);
  expect(work.items).toHaveLength(MAX_ITEMS);
});

it("returns zeros for an empty store", async () => {
  expect(await summariseWork(db)).toEqual({ unsent: 0, unsentFiles: 0, attention: 0, inProgress: 0, items: [] });
});

it("counts an interview with two photos once, and its files apart; both files stay separate items", async () => {
  await save("one", { valid: true });
  for (const id of ["f1", "f2"]) {
    await db.runAsync("INSERT INTO attachments (id, draft_id, question, kind, mime_type, ext, size_bytes, created_at, data) VALUES (?, ?, 'Id10001', 'photo', 'image/jpeg', 'jpg', 1, ?, x'00')", [id, "one", "2026-09-30"]);
  }
  const work = await summariseWork(db);
  expect(work).toMatchObject({ unsent: 1, unsentFiles: 2, attention: 0 });
  expect(work.items.filter((item) => item.kind === "attachment")).toHaveLength(2);
  await db.runAsync("UPDATE drafts SET upload_issue = 'answers_hash_invalid'", []);
  expect(await summariseWork(db)).toMatchObject({ unsent: 0, unsentFiles: 0, attention: 3 });
});

it("reads the deceased's name from each draft's Id10017 + Id10018 in one query", async () => {
  await save("both", undefined, { Id10017: "Mohan", Id10018: "Testcase" });
  await save("given", undefined, { Id10017: " Sunita " });
  await save("none");
  expect(await listDraftNames(db)).toEqual(new Map([["both", "Mohan Testcase"], ["given", "Sunita"]]));
});
