/** The WHO client over the engine (whoEngineApi.ts): the server's search options, caches, failure mapping, and the pinned engine release. */
import { readFileSync } from "node:fs";
import path from "node:path";

import type { EngineInit, EngineResult, OfflineEngine } from "../src/offlineEngine";
import { createWhoEngineApi, ENGINE_PROVENANCE, WHO_RELEASE, WhoUnavailableError } from "../src/workspace/whoEngineApi";

const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };
const ok = (data: unknown, status = 200): EngineResult => ({ ok: true, data, status, ms: 1, nativeMs: 1 });
const failed = (status?: number, error = "engine_status"): EngineResult => ({ ok: false, error, ...(status === undefined ? {} : { status }), ms: 1 });

type Handler = jest.Mock<Promise<EngineResult>, any[]>;
function fakeEngine(handlers: Partial<Record<"search" | "codeinfo" | "entity" | "foundationEntity" | "doris" | "codedit", Handler>> = {}) {
  const none = jest.fn(async () => failed(404)) as Handler;
  const engine: OfflineEngine = {
    available: async () => true,
    init: async () => init,
    warm: async () => init,
    updateWhoFiles: async () => init,
    call: async () => failed(400),
    search: handlers.search ?? none,
    codeinfo: handlers.codeinfo ?? none,
    entity: handlers.entity ?? none,
    foundationEntity: handlers.foundationEntity ?? none,
    doris: handlers.doris ?? none,
    codedit: handlers.codedit ?? none,
    onProgress: () => () => undefined,
  };
  return engine;
}

describe("search", () => {
  it("sends the server's options with a trailing % and a limit, never include=descendant", async () => {
    const search = jest.fn(async () => ok({ destinationEntities: [{ id: "a" }], resultChopped: true })) as Handler;
    const who = createWhoEngineApi(fakeEngine({ search }));
    await expect(who.search("  myocard  ", { limit: 20 })).resolves.toEqual({ entities: [{ id: "a" }], chopped: true });
    expect(search).toHaveBeenCalledWith("myocard%", {
      includePostcoordination: true, flatResults: true, highlightingEnabled: true, medicalCodingMode: true, limit: 20,
    });
    await who.search("x1", { limit: 5, subtreeUris: ["http://id.who.int/icd/entity/1", "http://id.who.int/icd/entity/2"] });
    expect(search).toHaveBeenLastCalledWith("x1%", expect.objectContaining({
      subtreesFilter: "http://id.who.int/icd/entity/1,http://id.who.int/icd/entity/2", limit: 5,
    }));
    await who.search("x1", { limit: 5, subtreeUris: [] });
    expect(search.mock.calls[2][1]).not.toHaveProperty("subtreesFilter");
    expect(JSON.stringify(search.mock.calls)).not.toContain("descendant");
  });

  it("is unavailable when the engine fails or answers something that is not a result list", async () => {
    await expect(createWhoEngineApi(fakeEngine({ search: jest.fn(async () => failed(500)) as Handler })).search("ab", { limit: 20 }))
      .rejects.toThrow(WhoUnavailableError);
    for (const data of [null, "text", { destinationEntities: "no" }, {}]) {
      await expect(createWhoEngineApi(fakeEngine({ search: jest.fn(async () => ok(data)) as Handler })).search("ab", { limit: 20 }))
        .rejects.toThrow(WhoUnavailableError);
    }
  });
});

describe("codeinfo", () => {
  it("returns WHO's record, caches it, and does not call the engine for a blank or over-long expression", async () => {
    const codeinfo = jest.fn(async () => ok({ code: "BA41.Z" })) as Handler;
    const who = createWhoEngineApi(fakeEngine({ codeinfo }));
    await expect(who.codeinfo(" BA41.Z ")).resolves.toEqual({ code: "BA41.Z" });
    await expect(who.codeinfo("BA41.Z")).resolves.toEqual({ code: "BA41.Z" });
    expect(codeinfo).toHaveBeenCalledTimes(1);
    expect(codeinfo).toHaveBeenCalledWith("BA41.Z");
    await expect(who.codeinfo("   ")).resolves.toBeNull();
    await expect(who.codeinfo("A".repeat(257))).resolves.toBeNull();
    expect(codeinfo).toHaveBeenCalledTimes(1);
  });

  it("treats a 404 as an answer (cached) and any other failure as unavailable (not cached)", async () => {
    const codeinfo = jest.fn(async (code: string) => (code === "NONE" ? failed(404) : code === "BAD" ? failed(400) : failed(undefined, "native_error"))) as Handler;
    const who = createWhoEngineApi(fakeEngine({ codeinfo }));
    await expect(who.codeinfo("NONE")).resolves.toBeNull();
    await expect(who.codeinfo("NONE")).resolves.toBeNull();
    expect(codeinfo).toHaveBeenCalledTimes(1);
    await expect(who.codeinfo("BAD")).rejects.toThrow(WhoUnavailableError);
    await expect(who.codeinfo("BAD")).rejects.toThrow(WhoUnavailableError);
    await expect(who.codeinfo("GONE")).rejects.toThrow(WhoUnavailableError);
    expect(codeinfo).toHaveBeenCalledTimes(4);
  });

  it("is unavailable when WHO's reply is not an object", async () => {
    const who = createWhoEngineApi(fakeEngine({ codeinfo: jest.fn(async () => ok(null)) as Handler }));
    await expect(who.codeinfo("BA41.Z")).rejects.toThrow(WhoUnavailableError);
  });
});

describe("entity", () => {
  it("reads a linearization entity, a residual child and a foundation entity by URI, and caches them", async () => {
    const entity = jest.fn(async (id: string) => ok({ id })) as Handler;
    const foundationEntity = jest.fn(async (id: string) => ok({ foundation: id })) as Handler;
    const who = createWhoEngineApi(fakeEngine({ entity, foundationEntity }));
    const base = "http://id.who.int/icd/release/11/2026-01/mms";
    await expect(who.entity(`${base}/1334938734`)).resolves.toEqual({ kind: "ok", entity: { id: "1334938734" } });
    await who.entity(`${base}/1334938734`);
    await expect(who.entity(`${base}/135352227/unspecified`)).resolves.toEqual({ kind: "ok", entity: { id: "135352227" } });
    await who.entity("http://id.who.int/icd/release/11/mms/7");
    expect(entity.mock.calls).toEqual([["1334938734", undefined], ["135352227", { residual: "unspecified" }], ["7", undefined]]);
    await expect(who.entity("http://id.who.int/icd/entity/911707612")).resolves.toEqual({ kind: "ok", entity: { foundation: "911707612" } });
    expect(foundationEntity).toHaveBeenCalledWith("911707612");
  });

  it("refuses a URI the server's proxy would refuse", async () => {
    const who = createWhoEngineApi(fakeEngine());
    for (const uri of ["http://id.who.int/icd/release/11/2026-01/mms", "https://id.who.int/icd/entity/1", "http://id.who.int/icd/release/11/2025-01/mms/1", "http://other/icd/entity/1", "http://id.who.int/icd/release/11/2026-01/mms/1/extra"]) {
      await expect(who.entity(uri)).rejects.toThrow(WhoUnavailableError);
    }
  });

  it("reads a 4xx or a non-object as no entity, and any other failure as unavailable", async () => {
    const entity = jest.fn(async (id: string) => (id === "1" ? failed(404) : id === "2" ? failed(400) : id === "3" ? ok("text") : id === "4" ? failed(500) : failed(undefined, "native_error"))) as Handler;
    const who = createWhoEngineApi(fakeEngine({ entity }));
    const uri = (id: number) => `http://id.who.int/icd/release/11/2026-01/mms/${id}`;
    await expect(who.entity(uri(1))).resolves.toEqual({ kind: "absent", status: 404 });
    await expect(who.entity(uri(2))).resolves.toEqual({ kind: "absent", status: 400 });
    await expect(who.entity(uri(3))).resolves.toEqual({ kind: "absent", status: 200 });
    await expect(who.entity(uri(4))).rejects.toThrow(WhoUnavailableError);
    await expect(who.entity(uri(5))).rejects.toThrow(WhoUnavailableError);
  });

  it("keeps at most 128 entities and forgets the oldest first", async () => {
    const entity = jest.fn(async (id: string) => ok({ id })) as Handler;
    const who = createWhoEngineApi(fakeEngine({ entity }));
    const uri = (id: number) => `http://id.who.int/icd/release/11/2026-01/mms/${id}`;
    for (let id = 1; id <= 129; id += 1) await who.entity(uri(id));
    expect(entity).toHaveBeenCalledTimes(129);
    await who.entity(uri(129)); // still cached
    expect(entity).toHaveBeenCalledTimes(129);
    await who.entity(uri(1)); // evicted
    expect(entity).toHaveBeenCalledTimes(130);
  });
});

describe("title", () => {
  const stem = "http://id.who.int/icd/release/11/2026-01/mms/10";

  it("uses codeinfo's own title, else the stem entity's, and caches each answer including 'none'", async () => {
    const codeinfo = jest.fn(async (code: string) => ok(
      code === "OWN" ? { code, title: "Own title" } : code === "VIA" ? { code, stemId: stem } : code === "LBL" ? { code, label: "<b>Label</b>", stemId: stem } : { code: "OTHER" },
    )) as Handler;
    const entity = jest.fn(async () => ok({ title: { "@value": "Entity title" } })) as Handler;
    const who = createWhoEngineApi(fakeEngine({ codeinfo, entity }));
    await expect(who.title("OWN")).resolves.toBe("Own title");
    await expect(who.title("VIA")).resolves.toBe("Entity title");
    await expect(who.title("LBL")).resolves.toBe("Label");
    await expect(who.title("MISMATCH")).resolves.toBe("");
    await who.title("MISMATCH");
    await who.title("OWN");
    expect(codeinfo).toHaveBeenCalledTimes(4);
  });

  it("is empty when WHO has no such code and unavailable when the answer is not about the code", async () => {
    const codeinfo = jest.fn(async (code: string) => (code === "UNKNOWN" ? failed(404) : ok({ code, stemId: code === "NOSTEM" ? 5 : code === "FOREIGN" ? "http://elsewhere/1" : stem }))) as Handler;
    let reply: EngineResult = failed(404);
    const entity = jest.fn(async () => reply) as Handler;
    const who = createWhoEngineApi(fakeEngine({ codeinfo, entity }));
    await expect(who.title("UNKNOWN")).resolves.toBe("");
    await expect(who.title("NOSTEM")).resolves.toBe("");
    await expect(who.title("FOREIGN")).resolves.toBe("");
    await expect(who.title("GONE")).resolves.toBe("");
    reply = ok("not an entity");
    await expect(who.title("TEXT")).resolves.toBe("");
    reply = failed(400);
    await expect(who.title("REFUSED")).rejects.toThrow(WhoUnavailableError);
    reply = failed(500);
    await expect(who.title("DOWN")).rejects.toThrow(WhoUnavailableError);
  });
});

describe("runProcessor", () => {
  it("returns the engine's reply, malformed for non-JSON, unavailable for anything else", async () => {
    const doris = jest.fn(async () => ok({ code: "X" })) as Handler;
    const codedit = jest.fn(async () => failed(undefined, "bad_json")) as Handler;
    const who = createWhoEngineApi(fakeEngine({ doris, codedit }));
    await expect(who.runProcessor("doris", { a: 1 })).resolves.toEqual({ kind: "ok", data: { code: "X" } });
    expect(doris).toHaveBeenCalledWith({ a: 1 });
    await expect(who.runProcessor("codedit", { a: 1 })).resolves.toEqual({ kind: "malformed" });
    const down = createWhoEngineApi(fakeEngine({ doris: jest.fn(async () => failed(500)) as Handler }));
    await expect(down.runProcessor("doris", {})).resolves.toEqual({ kind: "unavailable" });
  });
});

describe("pinned versions", () => {
  it("records the engine release that scripts/icd11-engine.env pins, and the ICD release the data ships", () => {
    const env = readFileSync(path.resolve(__dirname, "../../../scripts/icd11-engine.env"), "utf8");
    expect(/^ICD11_ENGINE_VERSION=(\S+)$/m.exec(env)?.[1]).toBe(ENGINE_PROVENANCE.icd11_engine);
    expect(ENGINE_PROVENANCE).toEqual({ icd11_engine: "2026.10.29.1", doris_engine: "1.1.176", doris_rules: "1.2.0", icd_release: "2026-01" });
    expect(WHO_RELEASE).toBe("2026-01");
  });
});
