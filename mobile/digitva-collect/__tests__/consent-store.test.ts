/** Phone consent rules: the gates, decision lookup, covered-answer stripping. Real SQLite. */
import { DatabaseSync } from "node:sqlite";

import { computeUtf8Sha256HexSync, type ConsentRecordEnvelope, type ProjectConsentConfig } from "../src/consent";
import {
  consentFor, coveredFieldsOf, DEFAULT_COVERED_FIELDS, inheritedConsentRefused, markInheritedConsentRefused, interviewConsentGate, loadConsents, registrationConsentGate, saveDraftConsent, saveRegistrationConsent, storedConsent, withoutCovered,
} from "../src/consentStore";
import { deleteDraft, migrate, type Db } from "../src/drafts";

jest.mock("expo-crypto", () => ({ CryptoDigestAlgorithm: { SHA256: "SHA-256" }, digestStringAsync: jest.fn() }));
jest.mock("expo-secure-store", () => ({}));

const memoryDb = (): Db => {
  const db = new DatabaseSync(":memory:");
  return {
    execAsync: async (sql) => void db.exec(sql),
    runAsync: async (sql, params) => db.prepare(sql).run(...params),
    getAllAsync: async <T,>(sql: string, params: Array<string | number | null>) => db.prepare(sql).all(...params) as T[],
    getFirstAsync: async <T,>(sql: string, params: Array<string | number | null>) => (db.prepare(sql).get(...params) as T | undefined) ?? null,
    closeAsync: async () => db.close(),
  };
};
const TEXT = "Notice";
const config = (over: Partial<ProjectConsentConfig> = {}): ProjectConsentConfig => ({
  project_id: "P1", consent_required: true, refusal_behaviour: "interview_without_informant_data",
  notice_versions: [{
    notice_version_id: "n1", version: 1, language: "en", text: TEXT, text_sha256: computeUtf8Sha256HexSync(TEXT),
    purposes: [{ code: "a", label: "A", required: true }], covered_fields: ["Id10007"], allowed_modes: ["spoken"], witness_allowed: false,
  }],
  contacts: { deletion: { email: "", phone: "" }, mentor_institution: {}, central_team: { email: "", phone: "" }, dpo: null, districts: {} },
  retention: { period_days: null, expiry_action: "erase" },
  ...over,
});
const envelope = (decision: "granted" | "refused"): ConsentRecordEnvelope => ({
  client_id: "c1", client_draft_id: null, notice_version_id: "n1", notice_language: "en", notice_sha256: computeUtf8Sha256HexSync(TEXT),
  decision, purposes: [{ code: "a", granted: decision === "granted" }], mode: "spoken", witness_present: false, supersedes_client_id: null, recorded_at: "2026-10-23T00:00:00Z",
});

describe("gates", () => {
  it("asks an interview only where consent is required and a notice is usable", () => {
    expect(interviewConsentGate(config())).toMatchObject({ state: "ask" });
    expect(interviewConsentGate(config({ consent_required: false }))).toEqual({ state: "off" });
  });

  it("locks the covered fields when settings are missing, a notice is unusable or the refusal behaviour is unknown", () => {
    for (const bad of [undefined, config({ notice_versions: [] }), config({ refusal_behaviour: "something_new" })]) {
      expect(interviewConsentGate(bad)).toMatchObject({ state: "unavailable", covered: expect.arrayContaining(["Id10007", "informant_name", "father_name"]) });
    }
    const tampered = config();
    tampered.notice_versions[0].text = "changed";
    expect(interviewConsentGate(tampered).state).toBe("unavailable");
  });

  it("always asks at registration when a notice exists, even where consent is not required, and never without one", () => {
    expect(registrationConsentGate(config({ consent_required: false })).state).toBe("ask");
    expect(registrationConsentGate(config({ notice_versions: [] })).state).toBe("unavailable");
    expect(registrationConsentGate(undefined).state).toBe("unavailable");
  });
});

describe("covered fields", () => {
  it("default to the server's list (consent_service.DEFAULT_COVERED_FIELDS), and the cached notice wins when there is one", () => {
    expect([...DEFAULT_COVERED_FIELDS].sort()).toEqual([
      "Id10007", "Id10055", "Id10057", "Id10061", "Id10062", "address", "address_house_street", "address_landmark",
      "address_village_ward", "father_name", "informant_name", "informant_phone", "informant_phone_2", "mother_name",
    ]);
    expect(coveredFieldsOf(config())).toEqual(["Id10007"]);
    expect(coveredFieldsOf(undefined)).toEqual([...DEFAULT_COVERED_FIELDS]);
  });
});

describe("stored decisions", () => {
  it("prefers the interview's own decision, then its registration's, then the case's", async () => {
    const db = memoryDb();
    await migrate(db);
    const own = storedConsent({ ...envelope("refused"), client_draft_id: "d1" }, config(), "u1");
    await saveDraftConsent(db, "d1", own);
    await saveRegistrationConsent(db, "reg1", storedConsent(envelope("granted"), config(), "u1"));
    const index = await loadConsents(db);
    expect(consentFor(index, { id: "d1", client_death_id: "reg1" })).toMatchObject({ own: true, record: { envelope: { decision: "refused" }, covered_fields: ["Id10007"], recorded_by: "u1" } });
    expect(consentFor(index, { id: "d2", client_death_id: "reg1" })).toMatchObject({ own: false, record: { envelope: { decision: "granted" } } });
    expect(consentFor(index, { id: "d3" })).toBeUndefined();
  });

  it("drops a draft's decision with the draft", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveDraftConsent(db, "d9", storedConsent(envelope("granted"), config(), "u1"));
    expect((await loadConsents(db)).has("consent:draft:d9")).toBe(true);
    await deleteDraft(db, "d9");
    expect((await loadConsents(db)).has("consent:draft:d9")).toBe(false);
  });
});

describe("an inherited decision the server refused", () => {
  it("flags only that draft, and the flag goes with a new own decision or the draft", async () => {
    const db = memoryDb();
    await migrate(db);
    await saveRegistrationConsent(db, "reg1", storedConsent(envelope("granted"), config(), "u1"));
    await markInheritedConsentRefused(db, "d1");
    expect(await inheritedConsentRefused(db, "d1")).toBe(true);
    expect(await inheritedConsentRefused(db, "d2")).toBe(false);
    expect((await loadConsents(db)).has("consent:reg:reg1")).toBe(true);
    await saveDraftConsent(db, "d1", storedConsent(envelope("granted"), config(), "u1"));
    expect(await inheritedConsentRefused(db, "d1")).toBe(false);
    await markInheritedConsentRefused(db, "d1");
    await deleteDraft(db, "d1");
    expect(await inheritedConsentRefused(db, "d1")).toBe(false);
  });
});

describe("withoutCovered", () => {
  it("drops only the covered keys and keeps the same object when none is present", () => {
    const data = { Id10007: "Asha", Id10013: "yes" };
    expect(withoutCovered(data, ["Id10007", "informant_name"])).toEqual({ Id10013: "yes" });
    expect(withoutCovered(data, ["informant_name"])).toBe(data);
  });
});
