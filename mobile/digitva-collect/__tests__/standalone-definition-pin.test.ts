/** Standalone drafts pin the bundled questionnaire (digitva-5bzf.12): a new draft stores the pin, a mismatch is read-only. */
import { DatabaseSync } from "node:sqlite";
import type { WhoVaDraft } from "@drguptavivek/who-2022-va";

import { createDraftStore, migrate, type Db } from "../src/drafts";
import { STANDALONE_DEFAULT_EXTENSIONS } from "../src/standalone/config";
import { standaloneDefinition, standaloneDraftMismatch } from "../src/standalone/project";

function memoryDb(): Db {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...(params as never[])),
    getAllAsync: async <T,>(sql: string, params: unknown[]) => db.prepare(sql).all(...(params as never[])) as T[],
    getFirstAsync: async <T,>(sql: string, params: unknown[]) => (db.prepare(sql).get(...(params as never[])) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
}

const definition = standaloneDefinition(STANDALONE_DEFAULT_EXTENSIONS);
const draft = (): WhoVaDraft => ({
  schemaVersion: 1, formVersion: "f1", id: "d1", instrumentId: "who-va-2022", instrumentVersion: definition.instrument.version,
  currentSection: "s1", createdAt: "2026-11-06T00:00:00Z", updatedAt: "2026-11-06T00:00:00Z", data: { Id10007: "A" } as never,
});

test("the bundled pin is a sha256 over the sorted extensions and is computed once", () => {
  expect(definition.pin).toMatchObject({ instrumentVersion: definition.instrument.version, definitionSha256: expect.stringMatching(/^[0-9a-f]{64}$/) });
  expect(definition.pin!.definitionExtensions).toEqual([...STANDALONE_DEFAULT_EXTENSIONS].sort());
  expect(standaloneDefinition([...STANDALONE_DEFAULT_EXTENSIONS].reverse()).pin).toBe(definition.pin);
  expect(standaloneDefinition([]).pin!.definitionSha256).not.toBe(definition.pin!.definitionSha256);
});

test("a new standalone draft stores the pin, and a matching pin stays editable", async () => {
  const db = memoryDb();
  await migrate(db);
  await createDraftStore(db, { projectId: "standalone-x", siteId: "standalone", definitionPin: definition.pin }).save(draft());
  const row = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = 'd1'", []);
  const envelope = JSON.parse(row!.envelope);
  expect(envelope.definitionSha256).toBe(definition.pin!.definitionSha256);
  expect(envelope.definitionExtensions).toEqual(definition.pin!.definitionExtensions);
  expect(standaloneDraftMismatch(envelope, definition)).toBe(false);
});

test("a label-only change (different hash or extensions) stays editable; a version change is read-only", () => {
  const stored = { ...draft(), definitionSha256: "0".repeat(64), definitionExtensions: [...definition.pin!.definitionExtensions] };
  expect(standaloneDraftMismatch(stored, definition)).toBe(false);
  expect(standaloneDraftMismatch({ ...stored, definitionExtensions: [] }, definition)).toBe(false);
  const pinned = { ...stored, definitionSha256: definition.pin!.definitionSha256 };
  expect(standaloneDraftMismatch({ ...pinned, instrumentVersion: "older" }, definition)).toBe(true);
  expect(standaloneDraftMismatch({ ...draft(), definitionSha256: "bad", definitionExtensions: [] }, definition)).toBe(true);
  expect(stored.data).toEqual({ Id10007: "A" });
});

test("a legacy draft without a pin is editable only when its version matches", () => {
  expect(standaloneDraftMismatch(draft(), definition)).toBe(false);
  expect(standaloneDraftMismatch({ ...draft(), instrumentVersion: "older" }, definition)).toBe(true);
});
