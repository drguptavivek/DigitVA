const mockAuthed = jest.fn();
const mockQueue = jest.fn();
jest.mock("../src/auth", () => {
  class SessionRevokedError extends Error {}
  class SignInRequiredError extends Error {}
  return { authedRequest: (...args: unknown[]) => mockAuthed(...args), SessionRevokedError, SignInRequiredError };
});
// The interviewer's encrypted queue: the supervisor flow must never reach its writers.
jest.mock("../src/revisions", () => ({
  ...jest.requireActual("../src/revisions"),
  beginRevision: mockQueue, queueRevision: mockQueue, createRevisionDraftStore: mockQueue,
}));
jest.mock("../src/phoneClock", () => ({ clockOffsetField: () => ({}) }));

import { ApiError } from "../src/api";
import { SessionRevokedError } from "../src/auth";
import { createRevisionSnapshot } from "../src/client/revisions";
import { t } from "../src/i18n";
import { leavesScreen, loadSupervisorDraft, sendFailureMessage, sendSupervisorRevision } from "../src/supervision/interviewRevision";

const target = { draft_id: "D1", va_sid: "VA1", project_id: "P1", site_id: "S1" };
const body = {
  draft: { ...target, death_id: "X1", status: "submitted", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z" },
  envelope: {
    id: "D1", schemaVersion: 1, formVersion: "2022", instrumentId: "WHO_2022_VA", instrumentVersion: "1", currentSection: "",
    createdAt: "2026-10-01T10:00:00Z", updatedAt: "2026-10-01T10:00:00Z", data: { Id10017: "Bina" },
  },
  prefill: {},
  answers_sha256: null,
};

beforeEach(() => { mockAuthed.mockReset(); mockQueue.mockReset(); });

describe("supervisor interview correction on the phone", () => {
  it("reads the draft over the bearer for its project and refuses a body about another interview", async () => {
    mockAuthed.mockResolvedValue({ status: 200, body });
    const row = await loadSupervisorDraft("u1", target);
    expect(mockAuthed).toHaveBeenCalledWith("u1", "/api/v1/intake/drafts/D1", { projectId: "P1" });
    expect(row.envelope.data).toEqual({ Id10017: "Bina" });
    mockAuthed.mockResolvedValue({ status: 200, body: { ...body, draft: { ...body.draft, project_id: "P2" } } });
    await expect(loadSupervisorDraft("u1", target)).rejects.toMatchObject({ code: "malformed_response" });
    expect(mockQueue).not.toHaveBeenCalled();
  });

  it("sends the frozen answers with the supervisor reason at once and the same snapshot twice", async () => {
    const snapshot = await createRevisionSnapshot({
      vaSid: "VA1", reasonCode: "supervisor_correction", data: { Id10017: "Binita" }, completion: { valid: true, issues: [] },
      draft: { startedAt: "2026-10-01T09:00:00+05:30", instrumentVersion: "1", definitionSha256: "a".repeat(64) }, generation: 0,
    });
    expect(snapshot.answersSha256).toMatch(/^[0-9a-f]{64}$/);
    mockAuthed.mockRejectedValueOnce(new TypeError("Network request failed"));
    await expect(sendSupervisorRevision("u1", "P1", snapshot)).rejects.toBeInstanceOf(TypeError);
    mockAuthed.mockResolvedValueOnce({ status: 200, body: { changed: true, va_sid: "VA1", answers_sha256: snapshot.answersSha256 } });
    await sendSupervisorRevision("u1", "P1", snapshot);
    const [first, second] = mockAuthed.mock.calls.map(([, path, init]) => ({ path, init, sent: init.bodyFactory() }));
    expect(second.path).toBe("/api/v1/intake/submissions/VA1/revisions");
    expect(second.init).toMatchObject({ method: "POST", projectId: "P1" });
    expect(second.sent).toMatchObject({
      reason_code: "supervisor_correction", answers_json: snapshot.answersJson, answers_sha256: snapshot.answersSha256,
      completion: { valid: true, issues: [] },
      draft: { startedAt: "2026-10-01T09:00:00+05:30", instrumentVersion: "1", definitionSha256: "a".repeat(64) },
    });
    expect(second.sent.answers_json).toBe(first.sent.answers_json);
    expect(second.sent).not.toHaveProperty("csrf");
    expect(mockQueue).not.toHaveBeenCalled();
  });

  it("refuses an acknowledgement for other answers", async () => {
    mockAuthed.mockResolvedValue({ status: 200, body: { changed: true, va_sid: "VA1", answers_sha256: "0".repeat(64) } });
    await expect(sendSupervisorRevision("u1", "P1", { vaSid: "VA1", reasonCode: "supervisor_correction", answersJson: "{}", answersSha256: "1".repeat(64), completion: { valid: true, issues: [] }, draft: { instrumentVersion: "1" }, generation: 0 }))
      .rejects.toMatchObject({ code: "malformed_response" });
  });

  it("stays on the form for a refused or failed send and leaves only for an account gate or a lost session", () => {
    for (const error of [new ApiError(409, "case_closed"), new ApiError(422, "answers_hash_invalid"), new ApiError(404, "not_found"), new TypeError("offline"), new ApiError(403, "forbidden")]) {
      expect(leavesScreen(error)).toBe(false);
    }
    expect(leavesScreen(new ApiError(403, "terms_required"))).toBe(true);
    expect(leavesScreen(new SessionRevokedError())).toBe(true);
  });

  it("words the refusals", () => {
    expect(sendFailureMessage(new ApiError(409, "case_closed"))).toBe(t("revisionCaseClosed"));
    expect(sendFailureMessage(new ApiError(409, "case_state_conflict"))).toBe(t("revisionCaseConflict"));
    expect(sendFailureMessage(new ApiError(422, "answers_hash_invalid"))).toBe(t("serverValidation"));
    expect(sendFailureMessage(new ApiError(404, "not_found"))).toBe(t("revisionUnavailable"));
  });
});
