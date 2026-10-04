import { createWhoVa2022Instrument, WHO_VA_FORM_VERSION, type SubmissionData, type WhoVaDraft } from "@drguptavivek/who-2022-va";

jest.mock("@drguptavivek/who-2022-va/web", () => ({ WhoVaForm: () => null }), { virtual: true });

import { RevisionMemoryStore } from "../src/client/revisionMemoryStore";
import { createRevisionSnapshot, getRevisionDetail, getSubmittedRevisions, isIncompleteOutcome, isPartialOutcome, postRevision, revisionOutcome } from "../src/client/revisions";
import { normalizeRevisionEnvelope } from "../src/web/InterviewScreen";

function response(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    redirected: false,
    url: "",
    headers: { get: (name: string) => name.toLowerCase() === "content-type" ? "application/json" : null } as Headers,
    json: async () => body,
    text: async () => "",
  } as Response;
}

const csrf = { header: "X-CSRFToken", token: "csrf" };
const validHash = "a".repeat(64);
const submittedDraft = {
  draft_id: "d1",
  project_id: "p1",
  site_id: "s1",
  unique_id: "case-1",
  status: "submitted" as const,
  va_sid: "va-1",
  created_at: "2026-10-04T10:00:00+05:30",
  updated_at: "2026-10-04T11:00:00+05:30",
};

afterEach(() => jest.restoreAllMocks());

describe("browser submitted interview revisions", () => {
  it("normalizes empty identity placeholders to the actual composed instrument and rejects mismatches", () => {
    const instrument = createWhoVa2022Instrument(["digitva_core"]);
    const envelope = {
      schemaVersion: 1 as const,
      formVersion: "",
      id: "d1",
      instrumentId: "",
      instrumentVersion: "",
      currentSection: "digitva_outcome",
      createdAt: submittedDraft.created_at,
      updatedAt: submittedDraft.updated_at,
      data: {},
    };
    expect(normalizeRevisionEnvelope(envelope, instrument)).toMatchObject({
      formVersion: WHO_VA_FORM_VERSION,
      instrumentId: instrument.id,
      instrumentVersion: instrument.version,
    });
    expect(normalizeRevisionEnvelope({ ...envelope, instrumentId: instrument.id, instrumentVersion: instrument.version, formVersion: WHO_VA_FORM_VERSION }, instrument)).toMatchObject({
      instrumentId: instrument.id,
      instrumentVersion: instrument.version,
    });
    expect(() => normalizeRevisionEnvelope({ ...envelope, formVersion: "other-form" }, instrument)).toThrow("revision_instrument_mismatch");
    expect(() => normalizeRevisionEnvelope({ ...envelope, instrumentId: "other-instrument" }, instrument)).toThrow("revision_instrument_mismatch");
    expect(() => normalizeRevisionEnvelope({ ...envelope, instrumentVersion: "other-version" }, instrument)).toThrow("revision_instrument_mismatch");
  });

  it("lists only the bounded submitted metadata endpoint with cookie CSRF", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, { drafts: [submittedDraft] }));
    await expect(getSubmittedRevisions(csrf)).resolves.toEqual([submittedDraft]);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/intake/drafts?status=submitted",
      expect.objectContaining({
        credentials: "include",
        cache: "no-store",
        headers: expect.objectContaining({ "X-CSRFToken": "csrf" }),
      }),
    );
  });

  it("rejects malformed or unbounded submitted metadata", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, { drafts: [{ ...submittedDraft, status: "draft" }] }));
    await expect(getSubmittedRevisions(csrf)).rejects.toMatchObject({ code: "malformed_response" });
    jest.restoreAllMocks();
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, { drafts: Array.from({ length: 201 }, (_, i) => ({ ...submittedDraft, draft_id: `d${i}` })) }));
    await expect(getSubmittedRevisions(csrf)).rejects.toMatchObject({ code: "malformed_response" });
  });

  it("loads raw answers on demand and accepts nullable or opaque stored hashes", async () => {
    const detail = {
      draft: { ...submittedDraft, updated_at: submittedDraft.updated_at },
      envelope: {
        schemaVersion: 1,
        formVersion: "2022",
        id: "d1",
        instrumentId: "who-2022-va",
        instrumentVersion: "1",
        currentSection: "digitva_outcome",
        createdAt: submittedDraft.created_at,
        updatedAt: submittedDraft.updated_at,
        locale: "hi",
        translation_version: 3,
        data: { interview_outcome: "partially_completed", Id10007: "raw" },
      },
      prefill: { lockedQuestionNames: ["Id10007"] },
      answers_sha256: validHash,
    };
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, detail));
    await expect(getRevisionDetail("/api/v1/intake/drafts", "d1", csrf, {
      draft_id: "d1", project_id: "p1", site_id: "s1", va_sid: "va-1",
    })).resolves.toMatchObject({ answers_sha256: validHash, envelope: { data: { Id10007: "raw" } } });
    expect(globalThis.fetch).toHaveBeenCalledWith(
      "/api/v1/intake/drafts/d1",
      expect.objectContaining({ credentials: "include", cache: "no-store" }),
    );

    jest.restoreAllMocks();
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, { ...detail, answers_sha256: null }));
    await expect(getRevisionDetail("/api/v1/intake/drafts", "d1", csrf)).resolves.toMatchObject({ answers_sha256: null });
  });

  it("freezes exact JSON text and fixed completion values for a retry", async () => {
    const data = { Id10007: "a", interview_outcome: "partially_completed" } as SubmissionData;
    const snapshot = await createRevisionSnapshot({
      vaSid: "va-1",
      reasonCode: "finish_partial",
      data,
      completion: { valid: true, issues: [] },
      draft: { startedAt: "2026-10-04T10:00:00+05:30", instrumentVersion: "served-2", definitionSha256: validHash, definitionExtensions: ["digitva_core"] },
      generation: 4,
    });
    expect(snapshot.answersJson).toBe(JSON.stringify(data));
    const digest = await globalThis.crypto.subtle.digest("SHA-256", new TextEncoder().encode(JSON.stringify(data)));
    const expectedHash = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
    expect(snapshot.answersSha256).toBe(expectedHash);
    expect(snapshot).toMatchObject({ reasonCode: "finish_partial", completion: { valid: true }, generation: 4 });
    expect(snapshot.draft.startedAt).toBe("2026-10-04T10:00:00+05:30");
    expect(snapshot.draft).toMatchObject({ instrumentVersion: "served-2", definitionSha256: validHash, definitionExtensions: ["digitva_core"] });
    expect(snapshot.draft.completedAt).toMatch(/T.*[+-]\d{2}:\d{2}$/);
  });

  it.each([true, false])("accepts complete matching acknowledgements when changed=%s", async (changed) => {
    const snapshot = await createRevisionSnapshot({
      vaSid: "va-1", reasonCode: "interviewer_correction", data: { Id10007: "x" } as SubmissionData,
      completion: { valid: true, issues: [] }, draft: { instrumentVersion: "served-2", definitionSha256: validHash, definitionExtensions: ["digitva_core"] }, generation: 0,
    });
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, {
      changed, va_sid: "va-1", payload_version_id: "version-2", answers_sha256: snapshot.answersSha256,
      outcome: "completed", workflow_state: "smartva_pending",
    }));
    await expect(postRevision(csrf, snapshot)).resolves.toMatchObject({ changed, va_sid: "va-1", answers_sha256: snapshot.answersSha256 });
    const [url, options] = (globalThis.fetch as jest.Mock).mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(String(options.body)) as Record<string, unknown>;
    expect(url).toBe("/api/v1/intake/submissions/va-1/revisions");
    expect(options.method).toBe("POST");
    expect((options.headers as Record<string, string>)["X-CSRFToken"]).toBe("csrf");
    expect(options.signal).toBeDefined();
    expect(body).toMatchObject({ reason_code: "interviewer_correction", answers_json: snapshot.answersJson, answers_sha256: snapshot.answersSha256 });
    expect(body.draft).toMatchObject({ instrumentVersion: "served-2", definitionSha256: validHash, definitionExtensions: ["digitva_core"] });
    expect(body.draft).toMatchObject({ deviceClockAt: expect.stringMatching(/T.*[+-]\d{2}:\d{2}$/) });
  });

  it("retains mismatched acknowledgements and safe refusals as failures", async () => {
    const snapshot = await createRevisionSnapshot({
      vaSid: "va-1", reasonCode: "more_information", data: {} as SubmissionData,
      completion: { valid: false, issues: [] }, draft: { instrumentVersion: "1" }, generation: 1,
    });
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(200, {
      changed: false, va_sid: "va-1", payload_version_id: "version-2", answers_sha256: validHash,
      outcome: "partially_completed", workflow_state: "paused",
    }));
    await expect(postRevision(csrf, snapshot)).rejects.toMatchObject({ code: "malformed_response" });
    jest.restoreAllMocks();
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response(409, { code: "revision_locked" }));
    await expect(postRevision(csrf, snapshot)).rejects.toMatchObject({ status: 409, code: "revision_locked" });
    jest.restoreAllMocks();
    jest.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("network"));
    await expect(postRevision(csrf, snapshot)).rejects.toThrow("network");
  });

  it("recognizes all incomplete outcomes and keeps the form store in memory with host metadata", async () => {
    expect(["partially_completed", "respondent_unavailable", "refused"].every(isIncompleteOutcome)).toBe(true);
    expect(["partially_completed", "respondent_unavailable"].every(isPartialOutcome)).toBe(true);
    expect(isPartialOutcome("refused")).toBe(false);
    expect(revisionOutcome({ Id10013: "no", interview_outcome: "partially_completed" } as SubmissionData, true)).toBe("refused");
    expect(revisionOutcome({ Id10013: " yes " } as SubmissionData, true)).toBe("completed");
    expect(revisionOutcome({ interview_outcome: "partially_completed" } as SubmissionData, true)).toBeUndefined();
    expect(revisionOutcome({ Id10013: " \t " } as SubmissionData, true)).toBeUndefined();
    expect(revisionOutcome({ Id10013: "yes", interview_outcome: "partially_completed" } as SubmissionData, true)).toBe("completed");
    expect(revisionOutcome({ Id10013: "yes", interview_outcome: "respondent_unavailable" } as SubmissionData, false)).toBe("respondent_unavailable");
    expect(isIncompleteOutcome("completed")).toBe(false);
    const original: WhoVaDraft & { startedAt: string; locale: string; translation_version: number; definitionSha256: string; definitionExtensions: string[] } = {
      schemaVersion: 1,
      formVersion: "2022",
      id: "d1",
      instrumentId: "who-2022-va",
      instrumentVersion: "1",
      currentSection: "s1",
      createdAt: "2026-10-04T10:00:00+05:30",
      updatedAt: "2026-10-04T11:00:00+05:30",
      startedAt: "2026-10-04T10:00:00+05:30",
      locale: "hi",
      translation_version: 3,
      definitionSha256: validHash,
      definitionExtensions: ["digitva_core"],
      data: { Id10007: "before" },
    };
    const store = new RevisionMemoryStore(original);
    store.save({ ...original, data: { Id10007: "after" }, locale: undefined } as unknown as WhoVaDraft);
    expect(store.load("d1")).toMatchObject({
      data: { Id10007: "after" }, startedAt: original.startedAt, locale: "hi", translation_version: 3,
      instrumentVersion: "1", definitionSha256: validHash, definitionExtensions: ["digitva_core"],
    });
    store.setLocaleMetadata("en", 0);
    store.save({ ...original, data: { Id10007: "later" }, locale: undefined } as unknown as WhoVaDraft);
    expect(store.getCurrent()).toMatchObject({ locale: "en", translation_version: 0 });
    store.remove("d1");
    expect(store.load("d1")).toBeUndefined();
  });
});
