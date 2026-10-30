/**
 * The offline DORIS editor against a fake engine: the replies are the server's (ApiError refusals included), personal
 * data never reaches the engine, an engine failure reads as the server's WHO_API_UNAVAILABLE and never carries the
 * engine's text, and a confirmed save produces the offline_coding row with the engine's provenance. The ports'
 * rules are tested in doris-terminology/-certificate/-processing and replayed against the server's recorded replies
 * in offline-who-golden.
 */
import { createHash, randomUUID } from "node:crypto";

import { ApiError } from "../src/api";
import { createOfflineDorisEditor, certificateSeedFromInterview, type OfflineCodingStore, type OfflineDorisEditor } from "../src/workspace/offlineDoris";
import type { OfflineCodingRow } from "../src/drafts";
import type { OfflineEngine, EngineResult, EngineInit } from "../src/offlineEngine";
import type { DorisProcessReply, JsonObject } from "../src/workspace/contracts";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, data: string) =>
    require("node:crypto").createHash("sha256").update(data, "utf8").digest("hex"),
  randomUUID: () => require("node:crypto").randomUUID(),
}));

const sha256 = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");
const ok = (data: unknown): EngineResult => ({ ok: true, data, status: 200, ms: 1, nativeMs: 1 });
const failed = (status?: number): EngineResult => ({ ok: false, error: "SECRET-STACK certificate text", ...(status === undefined ? {} : { status }), ms: 1 });
const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };

type Answers = Partial<Record<"search" | "codeinfo" | "entity" | "foundationEntity" | "doris" | "codedit", (...args: any[]) => Promise<EngineResult>>>;
/** A fake engine: whatever is not given answers a 404, and every call is recorded as [op, ...args]. */
function fakeEngine(answers: Answers = {}) {
  const calls: unknown[][] = [];
  const answer = (op: keyof Answers) => async (...args: unknown[]) => {
    calls.push([op, ...args]);
    return answers[op] ? answers[op]!(...args) : failed(404);
  };
  const engine: OfflineEngine = {
    available: async () => true,
    init: async () => init,
    warm: async () => init,
    updateWhoFiles: async () => init,
    call: async () => failed(400),
    search: answer("search"),
    codeinfo: answer("codeinfo"),
    entity: answer("entity"),
    foundationEntity: answer("foundationEntity"),
    doris: answer("doris"),
    codedit: answer("codedit"),
    onProgress: () => () => undefined,
  };
  return { engine, calls };
}

function memoryStore(): OfflineCodingStore & { rows: Map<string, OfflineCodingRow> } {
  const rows = new Map<string, OfflineCodingRow>();
  return {
    rows,
    save: async (row) => void rows.set(row.client_draft_id, row),
    get: async (clientDraftId) => rows.get(clientDraftId) ?? null,
  };
}

const MMS = "http://id.who.int/icd/release/11/2026-01/mms";
const BA41 = `${MMS}/1334938734/unspecified`;
const infos: Record<string, unknown> = {
  "BA41.Z": { code: "BA41.Z", stemId: BA41 },
  "1B12.2": { code: "1B12.2", stemId: `${MMS}/2` },
  XA0G74: { code: "XA0G74", stemId: `${MMS}/3` },
  "1B12.2&XA0G74": { code: "1B12.2&XA0G74", stemId: `${MMS}/2` },
  "1A00/GB00": { code: "1A00/GB00", stemCode: "1A00", stemId: `${MMS}/4`, hasCausingCondition: ["GB00"] },
  "1A00": { code: "1A00", stemId: `${MMS}/4` },
  GB00: { code: "GB00", stemId: `${MMS}/5` },
};
/** Codeinfo for the codes above, entity titles by id, a 404 for the rest. */
const knownWho: Answers = {
  codeinfo: async (code: string) => (code in infos ? ok(infos[code]) : failed(404)),
  entity: async (id: string) => ok({ title: { "@value": `Title ${id}` }, postcoordinationScale: [{ requiredPostcoordination: id === "1334938734" }] }),
};

const CERTIFICATE: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "AMI", Code: "BA41.Z", LinearizationURI: BA41 }] }] };

/** What an editor call refuses with: the ApiError's status, code, message and body. */
async function refusal(work: Promise<unknown>) {
  const error = await work.then(() => undefined, (caught: unknown) => caught);
  expect(error).toBeInstanceOf(ApiError);
  const api = error as ApiError;
  return { status: api.status, code: api.code, message: api.message, body: api.payload };
}
const errorBody = (code: string, message: string, extra: Record<string, unknown> = {}) => ({ schema_version: 1, error: { code, message, ...extra } });

describe("onTerms", () => {
  const entity = { theCode: "5A11", id: `${MMS}/9`, title: "<em>Type 2</em> diabetes", postcoordinationAvailability: 1, hasCodingNote: true };

  it("answers the server's terms reply from one engine search with the server's options", async () => {
    const { engine, calls } = fakeEngine({ search: async () => ok({ destinationEntities: [entity], resultChopped: false }) });
    const reply = await createOfflineDorisEditor(engine, memoryStore()).onTerms(" diabetes ", 5, ["http://id.who.int/icd/entity/1"]);
    expect(calls).toEqual([["search", "diabetes%", {
      includePostcoordination: true, flatResults: true, highlightingEnabled: true, medicalCodingMode: true,
      subtreesFilter: "http://id.who.int/icd/entity/1", limit: 20,
    }]]);
    expect(reply).toEqual({
      schema_version: 1, truncated: false, next_cursor: null,
      items: [{
        code: "5A11", title: "Type 2 diabetes", uri: `${MMS}/9`, release: "2026-01", matching_text: "Type 2 diabetes",
        postcoordination: true, postcoordination_availability: 1, related_maternal: false, related_perinatal: false, has_coding_note: true,
        extension: false,
      }],
    });
  });

  it("defaults the limit to 20 and reports truncation", async () => {
    const { engine } = fakeEngine({ search: async () => ok({ destinationEntities: [entity, entity], resultChopped: true }) });
    const reply = await createOfflineDorisEditor(engine, memoryStore()).onTerms("diabetes");
    expect(reply.items).toHaveLength(2);
    expect(reply.truncated).toBe(true);
  });

  it("refuses the requests the server refuses (422 INVALID_INPUT) without calling the engine", async () => {
    const { engine, calls } = fakeEngine();
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const invalid = { status: 422, code: "INVALID_INPUT", message: "The terminology request is invalid.", body: errorBody("INVALID_INPUT", "The terminology request is invalid.") };
    const bad: unknown[][] = [["a"], [" a "], ["x".repeat(81)], ["ab", 0], ["ab", 21], ["ab", 1.5], ["ab", 5, []], ["ab", 5, ["https://id.who.int/icd/x"]], [7]];
    for (const args of bad) await expect(refusal(editor.onTerms(...(args as [string, number?, string[]?])))).resolves.toEqual(invalid);
    expect(calls).toEqual([]);
  });

  it("does not send personal data: a phone number in the text or a subtree URI is refused before the engine", async () => {
    const { engine, calls } = fakeEngine();
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const query = await refusal(editor.onTerms("diabetes 9876543210"));
    expect(query).toMatchObject({ status: 422, code: "INVALID_INPUT", message: "The terminology request is invalid." });
    expect(query.body).toEqual(errorBody("INVALID_INPUT", "The terminology request is invalid.", {
      reason: "pii_boundary", fields: [{ path: "query", message: expect.stringContaining("PII boundary violation at query") }],
    }));
    expect(JSON.stringify(query)).not.toContain("9876543210");
    // A valid subtree URI shape (no whitespace) whose tail past "&" is a phone number: the number check refuses it.
    const subtree = await refusal(editor.onTerms("diabetes", 5, ["http://id.who.int/icd/x&9876543210"]));
    expect(subtree).toMatchObject({ status: 422, code: "INVALID_INPUT" });
    expect(subtree.body).toMatchObject({ error: { reason: "pii_boundary", fields: [{ path: "subtree_uris[0]" }] } });
    expect(calls).toEqual([]);
    // A WHO URI is not personal data even though its id is a 10-digit number.
    const sent = fakeEngine({ search: async () => ok({ destinationEntities: [], resultChopped: false }) });
    await expect(createOfflineDorisEditor(sent.engine, memoryStore()).onTerms("diabetes", 5, ["http://id.who.int/icd/release/11/2026-01/mms/9876543210"])).resolves.toMatchObject({ items: [] });
    expect(sent.calls).toHaveLength(1);
  });

  it("answers WHO_API_UNAVAILABLE (503) for any engine failure, never with the engine's text", async () => {
    for (const search of [async () => failed(500), async () => ok("not a result"), async () => ({ ok: false as const, error: "icd11_doris_disabled", ms: 0 })]) {
      const result = await refusal(createOfflineDorisEditor(fakeEngine({ search }).engine, memoryStore()).onTerms("diabetes"));
      expect(result).toEqual({ status: 503, code: "WHO_API_UNAVAILABLE", message: "WHO ICD-11 service unavailable.", body: errorBody("WHO_API_UNAVAILABLE", "WHO ICD-11 service unavailable.") });
      expect(JSON.stringify(result)).not.toContain("SECRET");
    }
  });

  it("passes through anything that is not a known failure", async () => {
    const { engine } = fakeEngine({ search: async () => { throw new TypeError("bug"); } });
    await expect(createOfflineDorisEditor(engine, memoryStore()).onTerms("diabetes")).rejects.toThrow(TypeError);
  });
});

describe("onCodeInfo", () => {
  it("answers the server's item: title from the stem entity, badges for a stem, the URI WHO reports", async () => {
    const { engine } = fakeEngine(knownWho);
    const reply = await createOfflineDorisEditor(engine, memoryStore()).onCodeInfo(" BA41.Z ");
    expect(reply).toEqual({
      schema_version: 1,
      item: {
        code: "BA41.Z", title: "Title 1334938734", uri: BA41, release: "2026-01", postcoordination: true,
        postcoordination_availability: 2, related_maternal: false, related_perinatal: false, has_coding_note: false,
        leaf: true, extension: false,
      },
    });
    expect(reply.item).not.toHaveProperty("primary_stem");
  });

  it("joins the part URIs of an expression and gives it no badges", async () => {
    const reply = await createOfflineDorisEditor(fakeEngine(knownWho).engine, memoryStore()).onCodeInfo("1B12.2&XA0G74");
    expect(reply.item).toEqual({ code: "1B12.2&XA0G74", title: "Title 2", uri: `${MMS}/2 & ${MMS}/3`, release: "2026-01", postcoordination: false, leaf: true, extension: false });
  });

  it("refuses an empty or over-long code (422 INVALID_INPUT), an unknown one (422 CODE_NOT_FOUND) and personal data", async () => {
    const { engine, calls } = fakeEngine(knownWho);
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const invalid = { status: 422, code: "INVALID_INPUT", message: "The code request is invalid.", body: errorBody("INVALID_INPUT", "The code request is invalid.") };
    await expect(refusal(editor.onCodeInfo("  "))).resolves.toEqual(invalid);
    await expect(refusal(editor.onCodeInfo("A".repeat(129)))).resolves.toEqual(invalid);
    await expect(refusal(editor.onCodeInfo(5 as unknown as string))).resolves.toEqual(invalid);
    expect(calls).toEqual([]);
    await expect(refusal(editor.onCodeInfo("ZZ99.9"))).resolves.toEqual({
      status: 422, code: "CODE_NOT_FOUND", message: "Select a valid ICD-11 code.", body: errorBody("CODE_NOT_FOUND", "Select a valid ICD-11 code."),
    });
    expect((await refusal(editor.onCodeInfo("9876543210"))).body).toMatchObject({ error: { reason: "pii_boundary" } });
    expect(calls.every(([op, code]) => op === "codeinfo" && code === "ZZ99.9")).toBe(true);
  });

  it("answers WHO_API_UNAVAILABLE when the engine fails", async () => {
    const result = await refusal(createOfflineDorisEditor(fakeEngine({ codeinfo: async () => failed(500) }).engine, memoryStore()).onCodeInfo("BA41.Z"));
    expect(result).toMatchObject({ status: 503, code: "WHO_API_UNAVAILABLE" });
    expect(JSON.stringify(result)).not.toContain("SECRET");
  });
});

describe("onSelectionCheck", () => {
  it("passes only with the URI WHO reports for the code, and remembers it for the save", async () => {
    const editor = createOfflineDorisEditor(fakeEngine(knownWho).engine, memoryStore());
    const reply = await editor.onSelectionCheck(" BA41.Z ", ` ${BA41} `);
    expect(reply.item).toMatchObject({ code: "BA41.Z", uri: BA41, postcoordination_availability: 2 });
    await expect(refusal(editor.onSelectionCheck("BA41.Z", "http://id.who.int/other"))).resolves.toEqual({
      status: 422, code: "INVALID_SELECTION", message: "The selected code does not match its WHO URI.", body: errorBody("INVALID_SELECTION", "The selected code does not match its WHO URI."),
    });
    await expect(refusal(editor.onSelectionCheck("ZZ99.9", BA41))).resolves.toMatchObject({ code: "INVALID_SELECTION" });
  });

  it("refuses an extension code alone and a category with children (422 INVALID_SELECTION, the server's words)", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      ...knownWho,
      entity: async (id: string) => ok({ title: { "@value": `Title ${id}` }, ...(id === "1334938734" ? { child: [`${MMS}/5`] } : {}) }),
    }).engine, memoryStore());
    const category = "BA41.Z is a category, not a final code. Choose a more specific code under it.";
    await expect(refusal(editor.onSelectionCheck("BA41.Z", BA41))).resolves.toEqual({
      status: 422, code: "INVALID_SELECTION", message: category, body: errorBody("INVALID_SELECTION", category),
    });
    const extension = "XA0G74 is an extension code. It cannot be used alone: add it to a stem through + Build.";
    await expect(refusal(editor.onSelectionCheck("XA0G74", `${MMS}/3`))).resolves.toMatchObject({ code: "INVALID_SELECTION", message: extension });
    await expect(editor.onSelectionCheck("1B12.2&XA0G74", `${MMS}/2 & ${MMS}/3`)).resolves.toMatchObject({ item: { leaf: true, extension: false } });
  });

  it("refuses a missing or over-long code or URI (422 INVALID_INPUT) and personal data in either", async () => {
    const { engine, calls } = fakeEngine(knownWho);
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const invalid = { status: 422, code: "INVALID_INPUT", message: "The selected ICD-11 code is invalid.", body: errorBody("INVALID_INPUT", "The selected ICD-11 code is invalid.") };
    for (const args of [[" ", BA41], ["BA41.Z", " "], ["A".repeat(129), BA41], ["BA41.Z", "u".repeat(2049)], [1, BA41], ["BA41.Z", 2]]) {
      await expect(refusal(editor.onSelectionCheck(...(args as [string, string])))).resolves.toEqual(invalid);
    }
    expect(calls).toEqual([]);
    expect((await refusal(editor.onSelectionCheck("9876543210", BA41))).body).toMatchObject({ error: { reason: "pii_boundary" } });
    expect((await refusal(editor.onSelectionCheck("BA41.Z", "x 9876543210"))).body).toMatchObject({ error: { reason: "pii_boundary" } });
    expect(calls).toEqual([]);
  });

  it("answers WHO_API_UNAVAILABLE when the engine fails", async () => {
    await expect(refusal(createOfflineDorisEditor(fakeEngine({ codeinfo: async () => failed() }).engine, memoryStore()).onSelectionCheck("BA41.Z", BA41))).resolves.toMatchObject({ status: 503 });
  });
});

describe("primaryStem", () => {
  it("is the first stem of a single code and WHO's causing condition for a cluster", async () => {
    const editor = createOfflineDorisEditor(fakeEngine(knownWho).engine, memoryStore());
    await expect(editor.primaryStem("ba41.z")).resolves.toBe("BA41.Z");
    await expect(editor.primaryStem("1A00/GB00")).resolves.toBe("GB00");
  });

  it("refuses what is not an expression, an unknown cluster, and an engine failure", async () => {
    const editor = createOfflineDorisEditor(fakeEngine(knownWho).engine, memoryStore());
    await expect(refusal(editor.primaryStem("not a code"))).resolves.toMatchObject({ status: 422, code: "INVALID_INPUT" });
    await expect(refusal(editor.primaryStem("1A00/5A12"))).resolves.toMatchObject({ status: 422, code: "CODE_NOT_FOUND" });
    await expect(refusal(editor.primaryStem("1A00/9Z9Z"))).resolves.toMatchObject({ status: 422, code: "CODE_NOT_FOUND" });
    await expect(refusal(createOfflineDorisEditor(fakeEngine({ codeinfo: async () => failed(500) }).engine, memoryStore()).primaryStem("1A00/GB00"))).resolves.toMatchObject({ status: 503, code: "WHO_API_UNAVAILABLE" });
  });
});

describe("onProcess (the server's process reply, token local)", () => {
  const dorisResult = { code: "BA41.Z", stemCode: "BA41.Z", uri: BA41, stemURI: BA41, report: "r", tabularReport: "t", reject: false, error: null, warning: null };
  const codeditResult = { report: "r", tabularReport: "t", issueIds: "" };
  const processing = (overrides: Answers = {}) => fakeEngine({
    ...knownWho,
    doris: async () => ok(dorisResult),
    codedit: async () => ok(codeditResult),
    ...overrides,
  });

  it("normalises the certificate, runs both engines and answers with the envelopes, UCOD parts and a local token", async () => {
    const { engine, calls } = processing();
    const reply: DorisProcessReply = await createOfflineDorisEditor(engine, memoryStore()).onProcess(3, CERTIFICATE);
    expect(reply).toMatchObject({
      schema_version: 1, client_revision: 3, icd_release: "2026-01",
      certificate: { ...CERTIFICATE, ICDMinorVersion: "2026-01" },
      doris: { status: "completed", result: dorisResult }, codedit: { status: "completed", result: codeditResult },
      who_notes: [], ucod_parts: [{ code: "BA41.Z", title: "AMI", role: "stem", uri: BA41 }],
    });
    expect(reply.process_token).toMatch(/^local-[0-9a-f-]{36}$/);
    // The certificate digest is the server's: SHA-256 of the canonical normalised certificate.
    expect(reply.certificate_digest).toBe(sha256(JSON.stringify({ ICDMinorVersion: "2026-01", ICDVersion: "ICD11", Part1: [{ Conditions: [{ Code: "BA41.Z", LinearizationURI: BA41, Text: "AMI" }] }] })));
    expect(reply.result_digest).toMatch(/^[0-9a-f]{64}$/);
    expect(calls.filter(([op]) => op === "doris" || op === "codedit").map(([op]) => op)).toEqual(["doris", "codedit"]);
  });

  it("keeps a rejected DORIS verdict as rejected and a failed CoDEdit as unavailable, without the engine's text", async () => {
    const { engine } = processing({
      doris: async () => ok({ ...dorisResult, reject: true, code: "", uri: "" }),
      codedit: async () => failed(500),
    });
    const reply = await createOfflineDorisEditor(engine, memoryStore()).onProcess(0, CERTIFICATE);
    expect(reply.doris.status).toBe("rejected");
    expect(reply.codedit).toEqual({ status: "unavailable", result: null });
    expect(reply.ucod_parts).toEqual([]);
    expect(JSON.stringify(reply)).not.toContain("SECRET-STACK");
  });

  it("refuses a certificate the server refuses with its fields (422 INVALID_INPUT), before any engine run", async () => {
    const { engine, calls } = processing();
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const result = await refusal(editor.onProcess(0, { ICDVersion: "ICD10", Part1: [] }));
    expect(result).toEqual({
      status: 422, code: "INVALID_INPUT", message: "The DORIS certificate is invalid.",
      body: errorBody("INVALID_INPUT", "The DORIS certificate is invalid.", { fields: [{ path: "certificate.ICDVersion", message: "Must be ICD11." }] }),
    });
    expect(calls).toEqual([]);
    const wrongUri = JSON.parse(JSON.stringify(CERTIFICATE));
    wrongUri.Part1[0].Conditions[0].LinearizationURI = `${BA41}x`;
    await expect(refusal(editor.onProcess(0, wrongUri))).resolves.toMatchObject({
      body: { error: { fields: [{ path: "certificate.Part1[0].Conditions[0].LinearizationURI", message: "Does not match the selected ICD-11 code." }] } },
    });
  });

  it("refuses a bad revision (422 INVALID_INPUT, the process request is invalid)", async () => {
    const { engine } = processing();
    await expect(refusal(createOfflineDorisEditor(engine, memoryStore()).onProcess(-1, CERTIFICATE))).resolves.toEqual({
      status: 422, code: "INVALID_INPUT", message: "The DORIS process request is invalid.", body: errorBody("INVALID_INPUT", "The DORIS process request is invalid."),
    });
  });

  it("never sends a certificate with personal data to the engine: the key or the number is refused first, naming the path only", async () => {
    const { engine, calls } = processing();
    const editor = createOfflineDorisEditor(engine, memoryStore());
    const withKey = await refusal(editor.onProcess(0, { ...CERTIFICATE, AdministrativeData: { informant_phone: "9876543210" } } as JsonObject));
    expect(withKey).toMatchObject({ status: 422, code: "INVALID_INPUT", message: "The DORIS certificate is invalid." });
    expect(withKey.body).toEqual(errorBody("INVALID_INPUT", "The DORIS certificate is invalid.", {
      reason: "pii_boundary", fields: [{ path: "certificate", message: expect.stringContaining("PII boundary violation at certificate.AdministrativeData.informant_phone") }],
    }));
    const withNumber = JSON.parse(JSON.stringify(CERTIFICATE));
    withNumber.Part1[0].Conditions[0].Text = "patient 2345 6789 0123";
    expect((await refusal(editor.onProcess(0, withNumber))).body).toMatchObject({ error: { reason: "pii_boundary" } });
    expect(JSON.stringify([withKey, calls])).not.toContain("9876543210");
    expect(calls).toEqual([]);
  });

  it("answers WHO_API_UNAVAILABLE when codeinfo cannot be read, and passes other errors through", async () => {
    await expect(refusal(createOfflineDorisEditor(processing({ codeinfo: async () => failed(500) }).engine, memoryStore()).onProcess(0, CERTIFICATE))).resolves.toMatchObject({ status: 503, code: "WHO_API_UNAVAILABLE" });
    await expect(createOfflineDorisEditor(processing({ codeinfo: async () => { throw new TypeError("bug"); } }).engine, memoryStore()).onProcess(0, CERTIFICATE)).rejects.toThrow(TypeError);
  });
});

describe("save (offline_coding row)", () => {
  const completedReply = async (editor: OfflineDorisEditor): Promise<DorisProcessReply> => await editor.onProcess(1, CERTIFICATE);

  /** The save tests confirm a code and process first, so the engine resolves its codeinfo and runs DORIS and CoDEdit. */
  const engineWithKnownCode = () => fakeEngine({
    ...knownWho,
    doris: async () => ok({ code: "BA41.Z", stemCode: "BA41.Z", uri: BA41, stemURI: BA41, report: "r", tabularReport: "t", reject: false, error: null, warning: null }),
    codedit: async () => ok({ report: "r", tabularReport: "t", issueIds: "" }),
  }).engine;

  function saveBody(overrides: Record<string, unknown> = {}): JsonObject {
    return {
      antecedent_cod: "BA41.Z",
      doris_certificate: CERTIFICATE,
      doris_result: { status: "completed", result: { code: "BA41.Z", reject: false } },
      codedit_result: { status: "completed", result: { report: "r", issueIds: [] } },
      doris_process_token: "local-token-1",
      doris_result_digest: "digest-1",
      doris_client_revision: 1,
      ...overrides,
    };
  }

  it("stores the certificate, engine bundles, digests, confirmed URI and provenance references", async () => {
    const store = memoryStore();
    const editor = createOfflineDorisEditor(engineWithKnownCode(), store);
    const reply = await completedReply(editor);
    await editor.onSelectionCheck("BA41.Z", BA41);
    const row = await editor.save({
      clientDraftId: "draft-1",
      body: saveBody(),
      reply,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: "2026-10-26T09:00:00.000+05:30",
      answersSha256: "c".repeat(64),
    });
    expect(row.status).toBe("coded");
    // Bound to the answers it was coded on (contract 17 coded_answers_sha256).
    expect(row.answers_sha256).toBe("c".repeat(64));
    expect(row.client_draft_id).toBe("draft-1");
    expect(JSON.parse(row.certificate)).toEqual(CERTIFICATE);
    expect(JSON.parse(row.result!)).toEqual({ status: "completed", result: { code: "BA41.Z", reject: false } });
    expect(row.process_token).toBe("local-token-1");
    expect(row.certificate_digest).toBe(reply.certificate_digest);
    expect(row.result_digest).toBe(reply.result_digest);
    expect(row.ucod_code).toBe("BA41.Z");
    expect(row.ucod_uri).toBe(BA41);
    // Which engine produced the coding; sync.ts sends it as pack_versions.
    expect(JSON.parse(row.provenance!)).toEqual({ packVersions: { icd11_engine: "2026.10.29.1", doris_engine: "1.1.176", doris_rules: "1.2.0", icd_release: "2026-01" } });
    expect(row.device_uuid).toBe("device-1");
    expect(row.coder_profile_updated_at).toBe("2026-10-26T09:00:00.000+05:30");
    expect(store.rows.get("draft-1")).toEqual(row);
  });

  it("maps a rejected verdict to rejected and a missing verdict to draft", async () => {
    const store = memoryStore();
    const editor = createOfflineDorisEditor(engineWithKnownCode(), store);
    await editor.save({
      clientDraftId: "draft-r",
      body: saveBody({ doris_result: { status: "rejected", result: { reject: true } } }),
      reply: null,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    });
    await editor.save({
      clientDraftId: "draft-u",
      body: saveBody({ doris_result: { status: "unavailable", result: null } }),
      reply: null,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    });
    expect(store.rows.get("draft-r")?.status).toBe("rejected");
    expect(store.rows.get("draft-u")?.status).toBe("draft");
  });

  it("keeps created_at across a re-save and refuses an unusable body", async () => {
    const store = memoryStore();
    const editor = createOfflineDorisEditor(engineWithKnownCode(), store);
    const first = await editor.save({
      clientDraftId: "draft-1",
      body: saveBody(),
      reply: await completedReply(editor),
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    });
    const second = await editor.save({
      clientDraftId: "draft-1",
      body: saveBody({ doris_process_token: "local-token-2" }),
      reply: await completedReply(editor),
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    });
    expect(second.created_at).toBe(first.created_at);
    expect(second.process_token).toBe("local-token-2");
    await expect(editor.save({
      clientDraftId: "draft-2",
      body: { antecedent_cod: "X" },
      reply: null,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    })).rejects.toThrow("offline_save_invalid");
    await expect(editor.save({
      clientDraftId: "  ",
      body: saveBody(),
      reply: null,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
    })).rejects.toThrow("offline_save_invalid");
  });

  it("stores source-clock coding milestones with the confirmed local save and keeps the first event on retry", async () => {
    const store = memoryStore();
    const editor = createOfflineDorisEditor(engineWithKnownCode(), store);
    const first = await editor.save({
      clientDraftId: "draft-timeline",
      body: saveBody(),
      reply: await completedReply(editor),
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
      workflowTimelineV1: [
        { event: "coding_opened", at: "2026-10-28T09:00:00+05:30" },
        { event: "doris_processed", at: "2026-10-28T09:04:00+05:30", elapsed_ms: 2000 },
      ],
    });
    const savedTimeline = JSON.parse(first.provenance!).workflowTimelineV1;

    expect(savedTimeline).toEqual([
      { event: "coding_opened", at: "2026-10-28T09:00:00+05:30" },
      { event: "doris_processed", at: "2026-10-28T09:04:00+05:30", elapsed_ms: 2000 },
      { event: "initial_saved", at: first.updated_at },
    ]);

    const retry = await editor.save({
      clientDraftId: "draft-timeline",
      body: saveBody(),
      reply: await completedReply(editor),
      deviceUuid: "device-1",
      coderProfileUpdatedAt: null,
      workflowTimelineV1: [{ event: "coding_opened", at: "2026-10-28T10:00:00+05:30" }],
    });

    expect(JSON.parse(retry.provenance!).workflowTimelineV1).toEqual(savedTimeline);
  });
});

describe("certificateSeedFromInterview", () => {
  it("seeds the administrative fields the interview answered, with provenance", () => {
    const seed = certificateSeedFromInterview({
      Id10019: "female",
      Id10022: "yes",
      Id10023: "2026-03-02",
      Id10020: "yes",
      Id10021: "1963-07-01",
      age_group: "adult",
      age_adult: "62",
      age_child_unit: "years",
    });
    expect(seed.certificate).toEqual({
      ICDVersion: "ICD11",
      AdministrativeData: { Sex: 2, DateDeath: "2026-03-02", DateBirth: "1963-07-01", EstimatedAge: "P62Y" },
    });
    expect(seed.provenance).toEqual({
      "AdministrativeData.Sex": { sources: ["Id10019"] },
      "AdministrativeData.DateDeath": { sources: ["Id10023"] },
      "AdministrativeData.DateBirth": { sources: ["Id10021"] },
      "AdministrativeData.EstimatedAge": { sources: ["age_adult"] },
    });
  });

  it("reads the partial birth keys and the neonate hour answer as the form stores them", () => {
    const seed = certificateSeedFromInterview({
      Id10019: "male",
      Id10022: "ref",
      Id10024: "2026",
      Id10020: "no",
      dob_precision: "month_year",
      dob_month_year: "2026-01",
      age_group: "neonate",
      age_neonate_days: 0,
      age_neonate_hours: 7,
    });
    expect(seed.certificate.AdministrativeData).toEqual({
      Sex: 1,
      DateDeath: "2026",
      DateBirth: "2026-01",
      EstimatedAge: "PT7H",
    });
  });

  it("drops odd answers and prefills nothing for an empty interview", () => {
    const odd = certificateSeedFromInterview({
      Id10019: "unknown-answer",
      Id10022: "yes",
      Id10023: "not-a-date",
      age_group: "adult",
      age_adult: 999,
    });
    expect(odd.certificate).toEqual({ ICDVersion: "ICD11" });
    expect(odd.provenance).toEqual({});
    expect(certificateSeedFromInterview({}).certificate).toEqual({ ICDVersion: "ICD11" });
  });
});
