/**
 * Golden replay of the server's DigitVA replies (scripts/icd11-golden/fixtures, recorded from the pinned WHO container
 * and the server's own rules) against the TypeScript port. A fake engine turns every `call(op, args)` into the WHO REST
 * request the server would have made and answers it from the fixture's recorded `who` replies; a call the fixture did
 * not record fails the test. The port must then produce the server's recorded reply exactly (digests and the process
 * token are not in the fixtures). Guidance operations (postcoordination, options, hierarchy, related, details) are WP3
 * and are only counted. A changed expectation is a reviewed re-record, never an edit here.
 */
import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { ApiError } from "../src/api";
import type { EngineInit, EngineOp, EngineResult, OfflineEngine } from "../src/offlineEngine";
import type { JsonObject } from "../src/workspace/contracts";
import { canonicalJson } from "../src/workspace/dorisCertificate";
import type { GuidanceEndpoint } from "../src/workspace/dorisGuidance";
import { createOfflineDorisEditor, type OfflineCodingStore, type OfflineDorisEditor } from "../src/workspace/offlineDoris";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, data: string) =>
    require("node:crypto").createHash("sha256").update(data, "utf8").digest("hex"),
  randomUUID: () => require("node:crypto").randomUUID(),
}));

const FIXTURES = path.resolve(__dirname, "../../../scripts/icd11-golden/fixtures");
const RELEASE_PATH = "icd/release/11/2026-01";
const GUIDANCE_ROUTE: Record<string, GuidanceEndpoint> = {
  postcoordination: "postcoordination",
  "postcoordination-options": "postcoordination-options",
  hierarchy: "hierarchy",
  "related-maternal": "related",
  "related-perinatal": "related",
  details: "details",
};
const HAVE_FIXTURES = existsSync(FIXTURES);

interface RecordedCall { method: string; path: string; request_body: string | null; status: number; reply?: unknown; reply_text?: string }
interface Operation { name: string; request: Record<string, unknown>; calls: string[]; reply: { http_status: number; body: Record<string, unknown> } }
interface Fixture { id: string; operations: Operation[]; built?: { expression: string; operations: Operation[] }[]; who: Record<string, RecordedCall> }

const load = (set: string, file: string): Fixture => JSON.parse(readFileSync(path.join(FIXTURES, set, file), "utf8"));
const files = (set: string): string[] => (HAVE_FIXTURES ? readdirSync(path.join(FIXTURES, set)).filter((name) => name.endsWith(".json")).sort() : []);

/** Python's urllib quote (safe="") and quote_plus, byte for byte. */
function pyQuote(text: string, plus = false): string {
  let out = "";
  for (const byte of Buffer.from(text, "utf8")) {
    const char = String.fromCharCode(byte);
    if (/[A-Za-z0-9_.\-~]/.test(char)) out += char;
    else if (plus && char === " ") out += "+";
    else out += `%${byte.toString(16).toUpperCase().padStart(2, "0")}`;
  }
  return out;
}

const SEARCH_ORDER = ["q", "includePostcoordination", "flatResults", "highlightingEnabled", "medicalCodingMode", "subtreesFilter"];

/** The WHO REST request the server makes for an engine call, as [method, path, body]. */
function restRequest(op: EngineOp, args: Record<string, unknown>): [string, string, string | null] {
  const only = (allowed: string[]) => {
    const extra = Object.keys(args).filter((key) => !allowed.includes(key));
    if (extra.length) throw new Error(`${op}: arguments the server never sends: ${extra.join(",")}`);
  };
  switch (op) {
    case "search": {
      only([...SEARCH_ORDER, "limit"]);
      const body = SEARCH_ORDER.filter((key) => key in args)
        .map((key) => `${key}=${pyQuote(String(args[key]), true)}`).join("&");
      return ["POST", `${RELEASE_PATH}/mms/search`, body];
    }
    case "codeinfo":
      only(["code"]);
      return ["GET", `${RELEASE_PATH}/mms/codeinfo/${pyQuote(String(args.code))}`, null];
    case "entity":
      only(["id", "residual"]);
      return ["GET", `${RELEASE_PATH}/mms/${args.id}${args.residual ? `/${args.residual}` : ""}`, null];
    case "foundation_entity":
      only(["id"]);
      return ["GET", `icd/entity/${args.id}`, null];
    case "doris":
    case "codedit":
      only(["certificate"]);
      return ["POST", `${RELEASE_PATH}/${op}`, canonicalJson(args.certificate)];
    default:
      throw new Error(`unexpected op ${op}`);
  }
}

/** An engine that answers only what the fixture recorded; `calls` and `unrecorded` are for the test to inspect. */
function replayEngine(fixture: Fixture) {
  const recorded = new Map<string, RecordedCall>();
  for (const call of Object.values(fixture.who)) recorded.set(`${call.method} ${call.path} ${call.request_body ?? ""}`, call);
  const calls: string[] = [];
  const unrecorded: string[] = [];
  const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };

  const call = async (op: EngineOp, input: Record<string, unknown>): Promise<EngineResult> => {
    const args = JSON.parse(JSON.stringify(input)) as Record<string, unknown>;
    const [method, resource, body] = restRequest(op, args);
    const key = `${method} ${resource} ${body ?? ""}`;
    calls.push(`${method} ${resource}`);
    const answer = recorded.get(key);
    if (!answer) {
      unrecorded.push(key);
      return { ok: false, error: "engine_status", status: 599, ms: 0 };
    }
    if (answer.status < 200 || answer.status > 299) return { ok: false, error: "engine_status", status: answer.status, ms: 0 };
    let data = JSON.parse(JSON.stringify(answer.reply));
    // The bridge's `limit` (not WHO's): keep the first `limit` entities and say so when it cut any.
    if (op === "search" && typeof args.limit === "number" && data.destinationEntities.length > args.limit) {
      data = { ...data, destinationEntities: data.destinationEntities.slice(0, args.limit), resultChopped: true };
    }
    return { ok: true, data, status: answer.status, ms: 0, nativeMs: 0 };
  };

  const engine: OfflineEngine = {
    available: async () => true,
    init: async () => init,
    updateWhoFiles: async () => init,
    call,
    search: (q, options) => call("search", { q, ...options }),
    codeinfo: (code, options) => call("codeinfo", { code, ...options }),
    entity: (id, options) => call("entity", { id, ...options }),
    foundationEntity: (id, options) => call("foundation_entity", { id, ...options }),
    doris: (certificate) => call("doris", { certificate }),
    codedit: (certificate) => call("codedit", { certificate }),
    onProgress: () => () => undefined,
  };
  return { engine, calls, unrecorded };
}

function editorFor(engine: OfflineEngine): OfflineDorisEditor {
  const store: OfflineCodingStore = { save: async () => undefined, get: async () => null };
  return createOfflineDorisEditor(engine, store);
}

/** What the port answers for a route request: the body, or the ApiError's status and body. */
async function answer(run: () => Promise<unknown>): Promise<{ http_status: number; body: unknown }> {
  try {
    return { http_status: 200, body: await run() };
  } catch (error) {
    if (!(error instanceof ApiError)) throw error;
    return { http_status: error.status, body: error.payload };
  }
}

const withoutProof = (body: unknown) => {
  const { certificate_digest: _c, result_digest: _r, process_token: _t, ...rest } = body as Record<string, unknown>;
  return rest;
};

/** The recorded calls the port made must all be among the ones the server made for this operation (it may make fewer: it caches). */
function expectCallsRecorded(made: string[], operation: Operation) {
  const allowed = new Set(operation.calls.map((key) => key.split(" #")[0]));
  expect(made.filter((key) => !allowed.has(key))).toEqual([]);
}

describe("golden fixtures are present", () => {
  it("finds the three sets", () => {
    expect(HAVE_FIXTURES).toBe(true);
    expect(files("search").length).toBeGreaterThan(200);
    expect(files("postcoordination").length).toBeGreaterThan(40);
    expect(files("doris").length).toBeGreaterThan(150);
  });
});

describe("search golden set: terms replies", () => {
  it.each(files("search"))("%s", async (file) => {
    const fixture = load("search", file);
    const [operation] = fixture.operations;
    const { engine, calls, unrecorded } = replayEngine(fixture);
    const reply = await answer(() => editorFor(engine).onTerms(operation.request.query as string, operation.request.limit as number));
    // The fixture keeps the top 5 in order and says how many there were.
    const body = reply.body as { items: unknown[] } & Record<string, unknown>;
    const actual = { ...body, item_count: body.items.length, items: body.items.slice(0, 5) };
    expect(reply.http_status).toBe(operation.reply.http_status);
    expect(actual).toEqual(operation.reply.body);
    expect(unrecorded).toEqual([]);
    expectCallsRecorded(calls, operation);
  });
});

describe("postcoordination golden set: codeinfo and selection-check", () => {
  const operationsOf = (fixture: Fixture) => [...fixture.operations, ...(fixture.built ?? []).flatMap((entry) => entry.operations)];

  it.each(files("postcoordination"))("%s", async (file) => {
    const fixture = load("postcoordination", file);
    for (const operation of operationsOf(fixture)) {
      if (operation.name in GUIDANCE_ROUTE) continue;
      const { engine, calls, unrecorded } = replayEngine(fixture);
      const editor = editorFor(engine);
      const reply = operation.name === "codeinfo"
        ? await answer(() => editor.onCodeInfo(operation.request.code as string))
        : await answer(() => editor.onSelectionCheck(operation.request.code as string, operation.request.uri as string));
      expect({ operation: operation.name, request: operation.request, ...reply }).toEqual({
        operation: operation.name, request: operation.request, ...operation.reply,
      });
      expect(unrecorded).toEqual([]);
      expectCallsRecorded(calls, operation);
    }
  });
});

describe("postcoordination golden set: guidance routes", () => {
  const operationsOf = (fixture: Fixture) => [...fixture.operations, ...(fixture.built ?? []).flatMap((entry) => entry.operations)];
  const replayed: Record<string, number> = {};
  const mostEngineCalls: Record<string, { calls: number; file: string }> = {};

  it.each(files("postcoordination"))("%s", async (file) => {
    const fixture = load("postcoordination", file);
    for (const operation of operationsOf(fixture)) {
      const endpoint = GUIDANCE_ROUTE[operation.name];
      if (!endpoint) continue;
      const { engine, calls, unrecorded } = replayEngine(fixture);
      const reply = await answer(() => editorFor(engine).onGuidance(endpoint, { schema_version: 1, ...operation.request }));
      expect({ operation: operation.name, request: operation.request, ...reply }).toEqual({
        operation: operation.name, request: operation.request, ...operation.reply,
      });
      expect(unrecorded).toEqual([]);
      expectCallsRecorded(calls, operation);
      replayed[operation.name] = (replayed[operation.name] ?? 0) + 1;
      if (calls.length > (mostEngineCalls[operation.name]?.calls ?? -1)) mostEngineCalls[operation.name] = { calls: calls.length, file };
    }
  });

  it("replayed every recorded guidance operation", () => {
    const recorded: Record<string, number> = {};
    for (const file of files("postcoordination")) {
      for (const operation of operationsOf(load("postcoordination", file))) {
        if (operation.name in GUIDANCE_ROUTE) recorded[operation.name] = (recorded[operation.name] ?? 0) + 1;
      }
    }
    const total = Object.values(recorded).reduce((sum, count) => sum + count, 0);
    expect(total).toBe(485);
    expect(replayed).toEqual(recorded);
    console.info(`postcoordination golden set: ${total} guidance operations replayed ${JSON.stringify(replayed)}; most engine calls per route ${JSON.stringify(mostEngineCalls)}`);
  });
});

describe("DORIS golden set: process replies", () => {
  it.each(files("doris"))("%s", async (file) => {
    const fixture = load("doris", file);
    const [operation] = fixture.operations;
    const { engine, calls, unrecorded } = replayEngine(fixture);
    const request = operation.request as { client_revision: number; certificate: JsonObject };
    const reply = await answer(() => editorFor(engine).onProcess(request.client_revision, request.certificate));
    expect(reply.http_status).toBe(operation.reply.http_status);
    expect(operation.reply.http_status === 200 ? withoutProof(reply.body) : reply.body).toEqual(operation.reply.body);
    expect(unrecorded).toEqual([]);
    expectCallsRecorded(calls, operation);
    if (operation.reply.http_status === 200) {
      // The digest of the normalised certificate is the server's, and the token is local.
      const proof = reply.body as { certificate_digest: string; process_token: string };
      expect(proof.certificate_digest).toBe(createHash("sha256").update(canonicalJson((operation.reply.body as { certificate: unknown }).certificate)).digest("hex"));
      expect(proof.process_token).toMatch(/^local-/);
    }
  });
});
