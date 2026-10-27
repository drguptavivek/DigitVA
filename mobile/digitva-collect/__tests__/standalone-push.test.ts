/**
 * Standalone (Path C) push after enrolment, offline contract section 17: the adoption offer, the exact body, the
 * reply's offline_coding verdicts, ack-before-delete, duplicate pushes, held refusals and stale coding.
 */
import { DatabaseSync } from "node:sqlite";
import { createHash } from "node:crypto";

import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";

const mockSecure = new Map<string, string>();
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async (_algorithm: string, value: string) => require("node:crypto").createHash("sha256").update(value, "utf8").digest("hex"),
  digest: async (_algorithm: string, data: Uint8Array) => require("node:crypto").createHash("sha256").update(data).digest().buffer,
}));
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("@drguptavivek/who-2022-va", () => ({
  createWhoVa2022Instrument: () => ({ id: "WHO_2022_VA", version: "v1", sections: [{ name: "start" }], questions: [] }),
  decodeWhoVaDraft: (value: unknown) => value,
  reduceNationalIdData: (data: unknown) => data,
}), { virtual: true });
jest.mock("../src/interviewerDb", () => ({ deleteInterviewerDb: jest.fn(async () => undefined), unsentWorkCount: jest.fn(async () => 1) }));
const DEVICE_UUID = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d";
jest.mock("../src/offlineIdentity", () => ({
  getOrCreatePlusDeviceIdentity: async () => ({ uuid: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d", created_at: "2026-10-01T00:00:00Z" }),
}));
jest.mock("../src/offlineProfile", () => ({
  getOfflineProfile: async () => ({
    name: " Dr Asha ", age_years: null, sex: null, designation: "Medical officer", facility_name: "PHC Rampur",
    country: "India", state: "", org_code: "PHC-01", hiv_mortality: null, malaria_mortality: null, updated_at: "2026-10-01T00:00:00Z",
  }),
}));

import { createDraftStore, getDraftRow, getMeta, getOfflineCoding, markCompleted, migrate, saveOfflineCoding, type Db, type OfflineCodingRow } from "../src/drafts";
import { draftAnswersSha256, isCodingStale, offlineCodingBody } from "../src/sync";
import { saveStandaloneConsent } from "../src/standaloneConsentStore";
import type { StandaloneConsentRecord } from "../src/standaloneConsent";
import { saveDraftConsent } from "../src/consentStore";
import {
  adoptionOffer,
  codingNoticeText,
  codingNotices,
  heldText,
  orgCodeClaim,
  pushStandaloneRecords,
  saveAdoption,
  standaloneCounts,
} from "../src/standalone/adopt";
import type { Account, Device } from "../src/auth";

const SERVER = "https://va.example.org";
const ENROLLED = "42";
const STANDALONE = `standalone-${DEVICE_UUID}`;
const DRAFT = "aaaaaaaa-0000-4000-8000-000000000001";
const ANSWERS: SubmissionData = { Id10013: "yes", Id10019: "female" };
const TOKEN = "local-11111111-2222-4333-8444-555555555555";
const sha = (text: string) => createHash("sha256").update(text, "utf8").digest("hex");

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

const draft = (data: SubmissionData = ANSWERS): WhoVaDraft => ({
  schemaVersion: 1, formVersion: "f1", id: DRAFT, instrumentId: "who-va-2022", instrumentVersion: "1",
  currentSection: "s1", createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-10-01T01:00:00Z", data,
});

const PROVENANCE = {
  allowability: { rules: "icd11-allowability-2026-01", release: "2026-01" },
  antecedent: { code: "BA41.Z", primary_stem: "BA41.Z", release: "2026-01" },
};

const CONSENT: StandaloneConsentRecord = {
  envelope: {
    client_id: "cccccccc-0000-4000-8000-000000000001", client_draft_id: DRAFT,
    notice_version_id: `standalone-${"e".repeat(64)}`, notice_language: "en", notice_sha256: "e".repeat(64),
    decision: "granted", purposes: [{ code: "interview", granted: true }], mode: "tap", witness_present: false,
    supersedes_client_id: null, recorded_at: "2026-10-01T00:00:00Z",
  } as StandaloneConsentRecord["envelope"],
  notice_text: "Notice text the respondent saw.",
  bundle_version: "2026-10-27",
  bundle_sha256: "f".repeat(64),
};

/** A completed standalone interview with its consent records (both, as the form saves them) and a coding. */
async function standaloneStore(options: { coded?: boolean } = {}): Promise<Db> {
  const db = memoryDb();
  await migrate(db);
  await createDraftStore(db, { projectId: STANDALONE, siteId: "standalone", binding: { projectId: STANDALONE } }).save(draft());
  await markCompleted(db, DRAFT, { valid: true, issues: [] });
  await saveDraftConsent(db, DRAFT, { envelope: CONSENT.envelope, project_id: STANDALONE, covered_fields: [], recorded_by: STANDALONE });
  await saveStandaloneConsent(db, DRAFT, CONSENT);
  if (options.coded !== false) await saveOfflineCoding(db, await codingRow(db));
  await saveAdoption(db, {
    userId: ENROLLED, userName: "Asha", server: SERVER, projectId: "P1", siteId: "S1", siteName: "P1 · S1", adoptedAt: "2026-10-27T00:00:00Z",
  });
  return db;
}

async function codingRow(db: Db, overrides: Partial<OfflineCodingRow> = {}): Promise<OfflineCodingRow> {
  return {
    client_draft_id: DRAFT,
    certificate: JSON.stringify({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Code: "BA41.Z" }] }] }),
    result: JSON.stringify({ status: "completed", result: { code: "BA41.Z" } }),
    codedit_result: JSON.stringify({ status: "completed", result: { report: "ok" } }),
    process_token: TOKEN,
    certificate_digest: "a".repeat(64),
    result_digest: "b".repeat(64),
    ucod_code: "BA41.Z",
    ucod_uri: "http://id.who.int/icd/entity/1",
    status: "coded",
    coder_profile_updated_at: "2026-10-01T00:00:00Z",
    device_uuid: DEVICE_UUID,
    provenance: JSON.stringify(PROVENANCE),
    answers_sha256: await draftAnswersSha256(db, DRAFT),
    created_at: "2026-10-01T02:00:00Z",
    updated_at: "2026-10-01T02:00:00Z",
    ...overrides,
  };
}

type Call = { url: string; auth?: string; body?: Record<string, unknown> };
let calls: Call[];
const json = (status: number, body: unknown) =>
  ({ ok: status >= 200 && status < 300, status, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) }) as unknown as Response;

/** The 3.6 reply for whatever was posted, plus the given offline_coding verdict. */
const accepted = (call: Call, offlineCoding?: unknown, status = 201) => json(status, {
  received_sha256: call.body?.answers_sha256, answers_sha256: call.body?.answers_sha256,
  kept: "incoming", locked: false, superseded: false, case: { death_id: "dddddddd-0000-4000-8000-000000000001", unique_id: "U-1", status: "submitted" },
  ...(offlineCoding === undefined ? {} : { offline_coding: offlineCoding }),
});

function server(submissions: (call: Call) => Response): void {
  calls = [];
  globalThis.fetch = jest.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const headers = init?.headers as Record<string, string> | undefined;
    const call: Call = { url: String(url), auth: headers?.Authorization, body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined };
    calls.push(call);
    if (call.url.endsWith("/submissions")) return submissions(call);
    return json(200, { roles: [], projects: [], user: { user_id: ENROLLED, name: "Asha" }, is_admin: false, demo_coding: { available: false, project_ids: [] } });
  }) as typeof fetch;
}
const submissionCalls = () => calls.filter(({ url }) => url.endsWith("/submissions"));

beforeEach(() => {
  mockSecure.clear();
  mockSecure.set("device", JSON.stringify({ device_id: "d1", server: SERVER, project_id: "P1", project_name: "P1" }));
  mockSecure.set("device_secret", "s");
  mockSecure.set("accounts", JSON.stringify([{ user_id: STANDALONE, name: "Asha", standalone: true }, { user_id: ENROLLED, name: "Asha" }]));
  mockSecure.set(`tokens.${ENROLLED}`, JSON.stringify({ access_token: "a", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" }));
});

/** What the store keeps for the interview: the draft, its coding and its standalone consent record. */
async function kept(db: Db) {
  return {
    draft: (await getDraftRow(db, DRAFT)) !== null,
    coding: (await getOfflineCoding(db, DRAFT)) !== null,
    consent: (await getMeta(db, `standaloneConsent:${DRAFT}`)) !== undefined,
  };
}
const ALL_KEPT = { draft: true, coding: true, consent: true };
const ALL_GONE = { draft: false, coding: false, consent: false };

describe("adoption offer", () => {
  const device: Device = { device_id: "d1", server: SERVER, project_id: "P1", project_name: "P1" };
  const accounts: Account[] = [{ user_id: STANDALONE, name: "Asha", standalone: true }, { user_id: ENROLLED, name: "Asha" }];

  it("is offered only on an enrolled phone whose standalone store holds interviews to send", async () => {
    const db = await standaloneStore();
    const counts = await standaloneCounts(db, DEVICE_UUID);
    expect(counts).toEqual({ interviews: 1, codings: 1, staleDraftIds: [], held: 0 });
    expect(adoptionOffer({ device, accounts, counts, adoption: null })).toEqual({ host: "va.example.org", targets: [accounts[1]] });

    const empty = memoryDb();
    await migrate(empty);
    const none = await standaloneCounts(empty, DEVICE_UUID);
    expect(none.interviews).toBe(0);
    expect(adoptionOffer({ device, accounts, counts: none, adoption: null })).toBeNull();
    expect(adoptionOffer({ device: undefined, accounts, counts, adoption: null })).toBeNull();
    expect(adoptionOffer({ device, accounts: [accounts[0]], counts, adoption: null })).toBeNull();
    expect(adoptionOffer({ device, accounts: [accounts[0], { ...accounts[1], needs_sign_in: true }], counts, adoption: null })).toBeNull();
    expect(adoptionOffer({ device, accounts, counts, adoption: { userId: ENROLLED } as never })).toBeNull();
  });

  it("sends the org code only when it matches the server's pattern", () => {
    expect(orgCodeClaim(" PHC-01 ")).toBe("PHC-01");
    expect(orgCodeClaim("DIST_07")).toBe("DIST_07"); // any tree level, not only a facility unit
    expect(orgCodeClaim("PHC Rampur")).toBeNull();
    expect(orgCodeClaim("")).toBeNull();
    expect(orgCodeClaim(undefined)).toBeNull();
  });
});

describe("push body", () => {
  it("is the section 17 upload exactly: standalone object, its consent record, and the fresh coding", async () => {
    const db = await standaloneStore();
    server((call) => accepted(call, { status: "pending", code: "not_ready" }));
    await pushStandaloneRecords(db);

    const [call] = submissionCalls();
    expect(call.auth).toBe("Bearer a");
    const answersJson = JSON.stringify(ANSWERS);
    // Built from the contract (offline-api-contract.md section 17), not from the sender.
    expect(call.body).toEqual({
      client_draft_id: DRAFT,
      project_id: "P1",
      site_id: "S1",
      draft: expect.objectContaining({ id: DRAFT, data: ANSWERS, deviceClockAt: expect.any(String) }),
      answers_json: answersJson,
      answers_sha256: sha(answersJson),
      completion: { valid: true, issues: [] },
      standalone: {
        client_device_uuid: DEVICE_UUID,
        profile_snapshot: { name: "Dr Asha", designation: "Medical officer", facility: "PHC Rampur", country: "India" },
        org_code: "PHC-01",
        consent: CONSENT,
      },
      offline_coding: {
        coded_answers_sha256: sha(answersJson),
        device_uuid: DEVICE_UUID,
        process_token: TOKEN,
        conclusive_cod: "BA41.Z",
        remark: null,
        certificate: { ICDVersion: "ICD11", Part1: [{ Conditions: [{ Code: "BA41.Z" }] }] },
        result: { status: "completed", result: { code: "BA41.Z" } },
        codedit_result: { status: "completed", result: { report: "ok" } },
        certificate_digest: "a".repeat(64),
        result_digest: "b".repeat(64),
        provenance: PROVENANCE,
        pack_versions: { allowability: "icd11-allowability-2026-01" },
      },
    });
    // The 5.3 consent key never travels beside standalone.consent (the server refuses both with 400).
    expect(call.body).not.toHaveProperty("consent");
    expect(call.body).not.toHaveProperty("org_unit_id");
  });

  it("sends no offline_coding for an interview that was never coded", async () => {
    const db = await standaloneStore({ coded: false });
    server((call) => accepted(call));
    await pushStandaloneRecords(db);
    expect(submissionCalls()[0].body).toHaveProperty("standalone");
    expect(submissionCalls()[0].body).not.toHaveProperty("offline_coding");
    expect(await kept(db)).toEqual({ draft: false, coding: false, consent: false });
  });
});

describe("reply handling", () => {
  it.each(["pending", "applied"] as const)("%s acknowledges: draft, coding and consent record are deleted only then", async (status) => {
    const db = await standaloneStore();
    expect(await kept(db)).toEqual(ALL_KEPT);
    server((call) => accepted(call, { status, code: status === "pending" ? "not_ready" : null }));
    const result = await pushStandaloneRecords(db);
    expect(result).toMatchObject({ sent: 1, failed: 0, codingOutcomes: [{ draftId: DRAFT, status }] });
    expect(await kept(db)).toEqual(ALL_GONE);
    expect(await codingNotices(db)).toEqual([]);
  });

  it("refused keeps the interview acknowledged and shows the refusal in plain text", async () => {
    const db = await standaloneStore();
    server((call) => accepted(call, { status: "refused", code: "coding_grant_required" }));
    const result = await pushStandaloneRecords(db);
    expect(result).toMatchObject({ sent: 1, codingOutcomes: [{ status: "refused", code: "coding_grant_required" }] });
    expect(await kept(db)).toEqual(ALL_GONE);
    const notices = await codingNotices(db);
    expect(notices).toEqual([{ draftId: DRAFT, code: "coding_grant_required", at: expect.any(String) }]);
    expect(codingNoticeText(notices[0].code)).toMatch(/no coding role/);
    for (const code of ["coding_mode_mismatch", "coded_version_superseded", "not_available", "forbidden"]) {
      expect(codingNoticeText(code)).not.toBe(codingNoticeText("coding_grant_required"));
    }
    expect(codingNoticeText("forbidden")).toContain("forbidden");
  });

  it("keeps everything when a coding was sent but the reply does not confirm it", async () => {
    const db = await standaloneStore();
    server((call) => accepted(call));
    await expect(pushStandaloneRecords(db)).rejects.toThrow("invalid_upload_ack");
    expect(await kept(db)).toEqual(ALL_KEPT);
  });

  it.each([
    [403, "device_mismatch", "standalone_refused", /not the device/],
    [422, "consent_invalid", "standalone_refused", /consent record/],
    [422, "offline_coding_invalid", "standalone_refused", /offline_coding_invalid/],
    [409, "conflict", "case_conflict", /another phone/],
  ])("%s %s is held and shown, not reopened or retried blindly", async (status, code, issue, text) => {
    const db = await standaloneStore();
    server(() => json(status, { error: "refused", code }));
    await expect(pushStandaloneRecords(db)).resolves.toMatchObject({ sent: 0, failed: 1 });
    const row = await getDraftRow(db, DRAFT);
    expect(row).toMatchObject({ completed: 1, upload_issue: issue });
    expect(await kept(db)).toEqual(ALL_KEPT);
    expect(heldText(code)).toMatch(text);
    // The next push does not send it again on its own.
    await pushStandaloneRecords(db);
    expect(submissionCalls()).toHaveLength(1);
  });
});

describe("network failure and duplicate pushes", () => {
  it("deletes nothing before the ack, and a resend of the same interview is the same request", async () => {
    const db = await standaloneStore();
    server(() => { throw new TypeError("Network request failed"); });
    await expect(pushStandaloneRecords(db)).rejects.toThrow(TypeError);
    expect(await kept(db)).toEqual(ALL_KEPT);
    const first = submissionCalls()[0].body!;

    // The server took the first one after all: the resend gets the first result (200) and the phone purges.
    server((call) => accepted(call, { status: "pending", code: "not_ready" }, 200));
    await expect(pushStandaloneRecords(db)).resolves.toMatchObject({ sent: 1 });
    const second = submissionCalls()[0].body!;
    expect(second.client_draft_id).toBe(first.client_draft_id);
    expect(second.answers_sha256).toBe(first.answers_sha256);
    expect(second.offline_coding).toEqual(first.offline_coding);
    expect(await kept(db)).toEqual(ALL_GONE);

    // A third push has nothing left to send.
    server((call) => accepted(call));
    await pushStandaloneRecords(db);
    expect(submissionCalls()).toHaveLength(0);
  });
});

describe("stale coding", () => {
  it("binds the coding to the answers it was made on", async () => {
    const db = await standaloneStore();
    const row = (await getOfflineCoding(db, DRAFT))!;
    const hash = (await draftAnswersSha256(db, DRAFT))!;
    expect(row.answers_sha256).toBe(hash);
    expect(isCodingStale(row, hash)).toBe(false);
    expect(isCodingStale(row, sha("other"))).toBe(true);
    expect(isCodingStale({ answers_sha256: null }, hash)).toBe(true);
    expect(offlineCodingBody(row, hash, DEVICE_UUID)).not.toBeNull();
    expect(offlineCodingBody({ ...row, status: "draft" }, hash, DEVICE_UUID)).toBeNull();
    expect(offlineCodingBody({ ...row, provenance: null }, hash, DEVICE_UUID)).toBeNull();
    expect(offlineCodingBody(row, hash, "99999999-9999-4999-8999-999999999999")).toBeNull();
  });

  it("does not send a coding whose answers changed afterwards, sends the interview, and says why", async () => {
    const db = await standaloneStore();
    // Reopened and edited after coding.
    await createDraftStore(db, { projectId: STANDALONE, siteId: "standalone", binding: { projectId: STANDALONE } }).save(draft({ ...ANSWERS, Id10019: "male" }));
    await markCompleted(db, DRAFT, { valid: true, issues: [] });
    expect(await standaloneCounts(db, DEVICE_UUID)).toMatchObject({ interviews: 1, codings: 0, staleDraftIds: [DRAFT] });

    server((call) => accepted(call));
    const result = await pushStandaloneRecords(db);
    expect(submissionCalls()[0].body).not.toHaveProperty("offline_coding");
    expect(result).toMatchObject({ sent: 1, staleCodingDraftIds: [DRAFT], codingOutcomes: [] });
    expect(await kept(db)).toEqual(ALL_GONE);
    expect((await codingNotices(db)).map((notice) => notice.code)).toEqual(["coded_version_superseded"]);
  });
});
