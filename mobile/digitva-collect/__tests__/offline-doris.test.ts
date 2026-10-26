/**
 * The offline DORIS editor against a fake engine: WHO payload mapping (the
 * server's rules), the local process reply, the error→unavailable rule, and
 * the offline_coding row a confirmed save produces.
 */
import { createHash, randomUUID } from "node:crypto";

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

/** A fake engine whose four ops answer canned results; the search/codeinfo/doris/codedit calls are recorded. */
function fakeEngine(overrides: {
  search?: (query: string) => Promise<EngineResult>;
  codeinfo?: (code: string) => Promise<EngineResult>;
  doris?: (certificate: unknown) => Promise<EngineResult>;
  codedit?: (certificate: unknown) => Promise<EngineResult>;
} = {}): OfflineEngine {
  const init: EngineInit = { ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true };
  return {
    available: async () => true,
    init: async () => init,
    updateWhoFiles: async () => init,
    search: overrides.search ?? (async () => ({ ok: true, data: {}, status: 200, ms: 1, nativeMs: 1 })),
    codeinfo: overrides.codeinfo ?? (async () => ({ ok: true, data: {}, status: 200, ms: 1, nativeMs: 1 })),
    doris: overrides.doris ?? (async () => ({ ok: true, data: { status: "unavailable", result: null }, status: 200, ms: 1, nativeMs: 1 })),
    codedit: overrides.codedit ?? (async () => ({ ok: true, data: { status: "unavailable", result: null }, status: 200, ms: 1, nativeMs: 1 })),
    onProgress: () => () => undefined,
  };
}

function memoryStore(): OfflineCodingStore & { rows: Map<string, OfflineCodingRow> } {
  const rows = new Map<string, OfflineCodingRow>();
  return {
    rows,
    save: async (row) => void rows.set(row.client_draft_id, row),
    get: async (clientDraftId) => rows.get(clientDraftId) ?? null,
  };
}

const CERTIFICATE: JsonObject = { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "AMI", Code: "BA41.Z" }] }] };

describe("onTerms (engine search → DorisTerm)", () => {
  it("maps WHO search entities the way the server does", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      search: async () => ({
        ok: true,
        status: 200,
        ms: 1,
        nativeMs: 1,
        data: {
          resultChopped: false,
          destinationEntities: [
            {
              theCode: "5A11",
              id: "http://id.who.int/icd/entity/119724091",
              title: "<em>Type 2</em> diabetes",
              matchingPVs: ["diabetes", "sugar"],
              postcoordinationAvailability: 1,
              hasMaternalChapterLink: true,
              hasPerinatalChapterLink: false,
              hasCodingNote: true,
            },
            { title: "no code" },
          ],
        },
      }),
    }), memoryStore());
    const reply = await editor.onTerms("diabetes", 20);
    expect(reply.items).toEqual([{
      code: "5A11",
      title: "Type 2 diabetes",
      uri: "http://id.who.int/icd/entity/119724091",
      release: "ICD-11",
      matching_text: "diabetes sugar",
      postcoordination: true,
      postcoordination_availability: 1,
      related_maternal: true,
      related_perinatal: false,
      has_coding_note: true,
    }]);
    // Server parity: an entity WHO answered without a usable code still counts as truncation.
    expect(reply.truncated).toBe(true);
    expect(reply.next_cursor).toBeNull();
  });

  it("falls back to the title for the matching text and reports truncation", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      search: async () => ({
        ok: true,
        status: 200,
        ms: 1,
        nativeMs: 1,
        data: {
          resultChopped: true,
          destinationEntities: [
            { theCode: "1B10.Z", id: "http://id.who.int/icd/entity/1", title: "Pulmonary tuberculosis" },
            { theCode: "1B11", id: "http://id.who.int/icd/entity/2", title: "Tuberculosis of lung" },
          ],
        },
      }),
    }), memoryStore());
    const reply = await editor.onTerms("tuberculosis", 1);
    expect(reply.items).toHaveLength(1);
    expect(reply.items[0]).toMatchObject({ code: "1B10.Z", matching_text: "Pulmonary tuberculosis", postcoordination: false, postcoordination_availability: null });
    expect(reply.truncated).toBe(true);
  });

  it("refuses without leaking the engine failure", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      search: async () => ({ ok: false, error: "stack trace with certificate text", ms: 1 }),
    }), memoryStore());
    await expect(editor.onTerms("diabetes")).rejects.toThrow("icd11_unavailable");
  });
});

describe("onCodeInfo / onSelectionCheck", () => {
  const engineWithCodeinfo = (records: Record<string, unknown>, fail = false) => fakeEngine({
    codeinfo: async (code) => fail
      ? { ok: false, error: "engine payload", ms: 1 }
      : { ok: true, status: 200, ms: 1, nativeMs: 1, data: records[code] ?? null },
  });

  it("maps a codeinfo record: title from WHO text, URI from the engine-reported stemId", async () => {
    const editor = createOfflineDorisEditor(engineWithCodeinfo({
      "BA41.Z": { code: "BA41.Z", stemId: "http://id.who.int/icd/entity/1334938734", title: "<em>Acute</em> myocardial infarction" },
    }), memoryStore());
    const reply = await editor.onCodeInfo("BA41.Z");
    expect(reply).toEqual({
      schema_version: 1,
      item: {
        code: "BA41.Z",
        title: "Acute myocardial infarction",
        uri: "http://id.who.int/icd/entity/1334938734",
        release: "2026-01",
        postcoordination: false,
      },
    });
  });

  it("joins the part URIs of a post-coordinated expression", async () => {
    const editor = createOfflineDorisEditor(engineWithCodeinfo({
      "1B12.2&XA0G74": { code: "1B12.2&XA0G74", stemId: "http://id.who.int/icd/entity/1", title: "TB with a device" },
      "1B12.2": { code: "1B12.2", stemId: "http://id.who.int/icd/entity/1", title: "Tuberculosis" },
      "XA0G74": { code: "XA0G74", stemId: "http://id.who.int/icd/entity/2", title: "Device" },
    }), memoryStore());
    const reply = await editor.onCodeInfo("1B12.2&XA0G74");
    expect(reply.item.uri).toBe("http://id.who.int/icd/entity/1 & http://id.who.int/icd/entity/2");
  });

  it("throws an unknown-code error when WHO does not know the code, the title, or the URI", async () => {
    const editor = createOfflineDorisEditor(engineWithCodeinfo({
      "ZZZ.Z": { code: "OTHER", stemId: "http://id.who.int/icd/entity/1", title: "Mismatched" },
      "NOTITLE": { code: "NOTITLE", stemId: "http://id.who.int/icd/entity/1" },
      "NOURI": { code: "NOURI", title: "No stem" },
    }), memoryStore());
    await expect(editor.onCodeInfo("ZZZ.Z")).rejects.toThrow("icd11_unknown_code");
    await expect(editor.onCodeInfo("NOTITLE")).rejects.toThrow("icd11_unknown_code");
    await expect(editor.onCodeInfo("NOURI")).rejects.toThrow("icd11_unknown_code");
    await expect(editor.onCodeInfo("")).rejects.toThrow("icd11_invalid_code");
  });

  it("a selection check passes only with the engine-reported URI, then remembers it", async () => {
    const store = memoryStore();
    const editor = createOfflineDorisEditor(engineWithCodeinfo({
      "BA41.Z": { code: "BA41.Z", stemId: "http://id.who.int/icd/entity/1334938734", title: "Acute myocardial infarction" },
    }), store);
    const reply = await editor.onSelectionCheck("BA41.Z", "http://id.who.int/icd/entity/1334938734");
    expect(reply.item.code).toBe("BA41.Z");
    await expect(editor.onSelectionCheck("BA41.Z", "http://id.who.int/other")).rejects.toThrow("icd11_uri_mismatch");
    await expect(editor.onSelectionCheck("BA41.Z", "http://id.who.int/icd/entity/1334938734")).resolves.toBeDefined();
  });

  it("refuses without leaking the engine failure", async () => {
    const editor = createOfflineDorisEditor(engineWithCodeinfo({}, true), memoryStore());
    await expect(editor.onCodeInfo("BA41.Z")).rejects.toThrow("icd11_unavailable");
  });
});

describe("onProcess (local DorisProcessReply)", () => {
  it("passes completed engine envelopes through and digests the JSON strings", async () => {
    const dorisEnvelope = { status: "completed", result: { code: "BA41.Z", stemCode: "BA41", reject: false, uri: "http://id.who.int/x" } };
    const codeditEnvelope = { status: "completed", result: { report: "r", tabularReport: "t", issueIds: [] } };
    const editor = createOfflineDorisEditor(fakeEngine({
      doris: async () => ({ ok: true, data: dorisEnvelope, status: 200, ms: 1, nativeMs: 1 }),
      codedit: async () => ({ ok: true, data: codeditEnvelope, status: 200, ms: 1, nativeMs: 1 }),
    }), memoryStore());
    const reply = await editor.onProcess(3, CERTIFICATE);
    expect(reply.schema_version).toBe(1);
    expect(reply.client_revision).toBe(3);
    expect(reply.icd_release).toBe("2026-01");
    expect(reply.certificate).toBe(CERTIFICATE);
    expect(reply.certificate_digest).toBe(sha256(JSON.stringify(CERTIFICATE)));
    expect(reply.result_digest).toBe(sha256(JSON.stringify({ doris: dorisEnvelope, codedit: codeditEnvelope })));
    expect(reply.doris).toEqual(dorisEnvelope);
    expect(reply.codedit).toEqual(codeditEnvelope);
    expect(reply.process_token).toMatch(/^local-[0-9a-f-]{36}$/);
  });

  it("keeps a rejected DORIS verdict as rejected", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      doris: async () => ({ ok: true, data: { status: "rejected", result: { code: "", reject: true } }, status: 200, ms: 1, nativeMs: 1 }),
    }), memoryStore());
    const reply: DorisProcessReply = await editor.onProcess(0, CERTIFICATE);
    expect(reply.doris.status).toBe("rejected");
    expect(reply.codedit.status).toBe("unavailable");
  });

  it("maps engine failures to unavailable and never carries the engine error text", async () => {
    const editor = createOfflineDorisEditor(fakeEngine({
      doris: async () => ({ ok: false, error: "SECRET-STACK certificate text", ms: 1 }),
      codedit: async () => ({ ok: true, status: 200, ms: 1, nativeMs: 1, data: { status: "nonsense", result: 42 } }),
    }), memoryStore());
    const reply = await editor.onProcess(0, CERTIFICATE);
    expect(reply.doris).toEqual({ status: "unavailable", result: null });
    expect(reply.codedit).toEqual({ status: "unavailable", result: null });
    expect(JSON.stringify(reply)).not.toContain("SECRET-STACK");
  });
});

describe("save (offline_coding row)", () => {
  const completedReply = async (editor: OfflineDorisEditor): Promise<DorisProcessReply> => await editor.onProcess(1, CERTIFICATE);

  /** The save tests confirm a code first, so the engine resolves its codeinfo record. */
  const engineWithKnownCode = () => fakeEngine({
    codeinfo: async (code) => code === "BA41.Z"
      ? { ok: true, status: 200, ms: 1, nativeMs: 1, data: { code, stemId: "http://id.who.int/icd/entity/1334938734", title: "Acute myocardial infarction" } }
      : { ok: true, status: 200, ms: 1, nativeMs: 1, data: null },
  });

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
    await editor.onSelectionCheck("BA41.Z", "http://id.who.int/icd/entity/1334938734");
    const row = await editor.save({
      clientDraftId: "draft-1",
      body: saveBody(),
      reply,
      deviceUuid: "device-1",
      coderProfileUpdatedAt: "2026-10-26T09:00:00.000+05:30",
    });
    expect(row.status).toBe("coded");
    expect(row.client_draft_id).toBe("draft-1");
    expect(JSON.parse(row.certificate)).toEqual(CERTIFICATE);
    expect(JSON.parse(row.result!)).toEqual({ status: "completed", result: { code: "BA41.Z", reject: false } });
    expect(row.process_token).toBe("local-token-1");
    expect(row.certificate_digest).toBe(reply.certificate_digest);
    expect(row.result_digest).toBe(reply.result_digest);
    expect(row.ucod_code).toBe("BA41.Z");
    expect(row.ucod_uri).toBe("http://id.who.int/icd/entity/1334938734");
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
