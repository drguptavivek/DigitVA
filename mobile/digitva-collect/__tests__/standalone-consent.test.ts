import { computeUtf8Sha256HexSync } from "../src/consent";
import {
  buildStandaloneConsentRecord,
  getStandaloneConsentNotice,
  standaloneDefaultPurposes,
} from "../src/standaloneConsent";
import { getStandaloneConsent, saveStandaloneConsent } from "../src/standaloneConsentStore";

const SEED_CODES = [
  "cause_of_death_coding", "contact_followup", "messages", "narrative_automated_processing",
  "record_and_interview", "research_sharing", "statistics_reports",
];

describe("standalone consent notice", () => {
  it.each(["en", "hi"])("%s: fills placeholders and shows no brackets", (language) => {
    const filled = getStandaloneConsentNotice(language, { projectName: "Pilot VA", organisation: "AIIMS Delhi" })!;
    expect(filled.text).toContain("Pilot VA");
    expect(filled.purposes.find((p) => p.code === "narrative_automated_processing")!.label).toContain("AIIMS Delhi");
    const blank = getStandaloneConsentNotice(language, { projectName: " ", organisation: null })!;
    for (const n of [filled, blank]) {
      expect(n.text).not.toMatch(/[\[\]]/);
      n.purposes.forEach((p) => expect(p.label).not.toMatch(/[\[\]]/));
    }
    expect(blank.text).toContain(language === "en" ? "the study team" : "अध्ययन दल");
    expect(filled.text_sha256).toBe(computeUtf8Sha256HexSync(filled.text));
    expect(filled.text_sha256).not.toBe(blank.text_sha256);
  });

  it("has the seed's purpose codes with item 7 optional and defaulting to no", () => {
    const notice = getStandaloneConsentNotice("en")!;
    expect(notice.purposes.map((p) => p.code).sort()).toEqual(SEED_CODES);
    expect(notice.purposes.find((p) => p.code === "narrative_automated_processing")!.required).toBe(false);
    const defaults = standaloneDefaultPurposes(notice);
    expect(defaults.narrative_automated_processing).toBe(false);
    expect(defaults.record_and_interview).toBe(true);
  });

  it("returns null for a language the app does not bundle", () => {
    expect(getStandaloneConsentNotice("ta")).toBeNull();
    expect(getStandaloneConsentNotice("")).toBeNull();
  });

  it("stores the answers, rendered snapshot, version and sha with the record", async () => {
    const notice = getStandaloneConsentNotice("en", { projectName: "Pilot VA" })!;
    const record = buildStandaloneConsentRecord({
      notice, clientId: "c1", clientDraftId: "d1", decision: "granted", mode: "tap", witnessPresent: false,
      recordedAt: "2026-10-27T00:00:00Z",
    });
    expect(record.notice_text).toBe(notice.text);
    expect(record.notice_text).toContain("Pilot VA");
    expect(record.envelope.notice_sha256).toBe(computeUtf8Sha256HexSync(record.notice_text));
    expect(record.envelope.notice_version_id).toBe(`standalone-${record.envelope.notice_sha256}`);
    expect(record.bundle_version).toMatch(/^seed-/);
    expect(record.bundle_sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(record.envelope.purposes.map((p) => p.code)).toEqual(SEED_CODES);
    expect(record.envelope.purposes.find((p) => p.code === "narrative_automated_processing")!.granted).toBe(false);
    expect(record.envelope.mode).toBe("tap");

    const store = new Map<string, string>();
    const db = {
      runAsync: async (_sql: string, [k, v]: string[]) => { store.set(k, v); },
      getFirstAsync: async (_sql: string, [k]: string[]) => (store.has(k) ? { value: store.get(k) } : null),
    } as never;
    await saveStandaloneConsent(db, "d1", record);
    expect(await getStandaloneConsent(db, "d1")).toEqual(record);
  });
});
