/**
 * Characterization of every error-to-message mapping before they share src/errorMessages.ts
 * (bead r8nh.23): the phone's errorText, the browser's browserErrorText, the revision messages and
 * the interview-row revision status. Pins the key shown per input, whether a Ref line follows, and the
 * phone's recordError side effect. Web-vs-phone differences are pinned as they are today, on purpose.
 */
jest.mock("../src/errorLog", () => ({
  ...jest.requireActual("../src/errorLog"),
  recordError: jest.fn(),
}));

import { ApiError, ClientApiError } from "../src/api";
import { AccountStoreCollisionError, AlreadyEnrolledError, NotInSlotError, SessionRevokedError, SignInRequiredError } from "../src/authErrors";
import { recordError } from "../src/errorLog";
import { FormDefinitionError } from "../src/formDefinitions";
import { PinnedDefinitionError } from "../src/formDefinitionRuntime";
import { t, type StringKey } from "../src/i18n";
import { OfflineError } from "../src/network";
import { attentionMessage, loadFailureMessage } from "../src/revisionMessages";
import { localRevisionStatus } from "../src/ui/interviewRows";
import { errorText } from "../src/ui";
import { browserErrorText } from "../src/web/common";

const REF = /\nRef: .+ · \d\d:\d\dZ · v.+$/;

/** The key's text, with or without the trailing Ref line. */
function expectKey(actual: string, key: StringKey, withRef: boolean) {
  if (withRef) {
    expect(actual).toMatch(REF);
    expect(actual.replace(REF, "")).toBe(t(key));
  } else {
    expect(actual).toBe(t(key));
  }
}

type Row = [code: string | undefined, status: number, phoneKey: StringKey, phoneRef: boolean, webKey: StringKey, webRef: boolean];
const G = "errGeneric" as const;
// [code, status, phone key, phone Ref line, web key, web Ref line]
const ROWS: Row[] = [
  ["device_limit", 403, "deviceLimit", false, "serverForbidden", false],
  ["enrolment_invalid", 400, "errEnrolInvalid", false, "serverValidation", true],
  ["csrf_failed", 403, "csrfRefreshed", false, "serverForbidden", false],
  ["csrf_failed", 400, "csrfRefreshed", false, "csrfRefreshed", false],
  ["cookie_session_required", 401, "loginRequiredAction", false, "serverUnauthorized", false],
  ["cookie_session_required", 400, "loginRequiredAction", false, "serverValidation", true],
  ["maintenance", 503, "serverUnavailable", false, "serverUnavailable", true],
  ["maintenance", 200, "serverUnavailable", false, "serverError", true],
  ["redirected_response", 502, "serverUnavailable", false, "serverUnavailable", true],
  ["redirected_response", 503, "serverUnavailable", false, "serverUnavailable", true],
  ["redirected_response", 504, "serverUnavailable", false, "serverUnavailable", true],
  ["redirected_response", 200, G, true, "serverError", true],
  ["redirected_response", 500, G, true, "serverUnavailable", true],
  ["not_in_your_training_set", 403, "errNotInTrainingSet", false, "serverForbidden", false],
  ["role_not_in_session_type", 403, "errRoleNotInSessionType", false, "serverForbidden", false],
  ["corpus_missing", 409, "errCorpusMissing", false, "serverError", true],
  ["corpus_cases_ineligible", 409, "errCorpusMissing", false, "serverError", true],
  ["app_update_required", 426, "errAppUpdateRequired", false, "serverError", true],
  ["forbidden", 403, "serverForbidden", false, "serverForbidden", false],
  ["project_forbidden", 403, "serverForbidden", false, "serverForbidden", false],
  ["password_change_required", 403, "termsRequired", false, "serverForbidden", false],
  ["terms_required", 403, "termsRequired", false, "loginRequiredAction", false],
  ["email_unverified", 403, "errAccountNotActivated", false, "serverForbidden", false],
  ["no_interviewer_grant", 403, "errNoGrant", false, "serverForbidden", false],
  ["project_intake_off", 403, "errProjectIntakeOff", false, "serverForbidden", false],
  ["no_collection_access", 403, "noCollectionAccess", false, "serverForbidden", false],
  ["device_revoked", 401, "errDeviceRevoked", false, "serverUnauthorized", false],
  ["demo_limit", 403, "demoLimit", false, "serverForbidden", false],
  ["cap_reached", 409, "demoFull", false, "serverError", true],
  ["unauthorized", 401, "errSignIn", false, "serverUnauthorized", false],
  ["unauthorized", 403, G, true, "serverUnauthorized", false],
  [undefined, 401, "errSignIn", false, "serverUnauthorized", false],
  ["some_future_code", 401, "errSignIn", false, "serverUnauthorized", false],
  ["some_future_code", 403, G, true, "serverForbidden", false],
  [undefined, 429, "errRateLimited", false, "serverError", true],
  ["rate_limited", 429, "errRateLimited", false, "serverError", true],
  [undefined, 422, G, true, "serverValidation", true],
  [undefined, 400, G, true, "serverValidation", true],
  [undefined, 404, G, true, "serverError", true],
  [undefined, 409, G, true, "serverError", true],
  [undefined, 500, G, true, "serverUnavailable", true],
  [undefined, 503, G, true, "serverUnavailable", true],
  ["malformed_response", 200, G, true, "serverError", true],
];

describe("errorText (phone) and browserErrorText (web) for an ApiError", () => {
  beforeEach(() => (recordError as jest.Mock).mockClear());

  it.each(ROWS)("%s / %s", (code, status, phoneKey, phoneRef, webKey, webRef) => {
    const error = new ApiError(status, code);
    expectKey(errorText(error), phoneKey, phoneRef);
    expectKey(browserErrorText(error), webKey, webRef);
    expect(ClientApiError).toBe(ApiError);
  });

  it("files exactly one scrubbed entry per phone call, and none from the web", () => {
    const error = new ApiError(422, "x");
    errorText(error);
    expect(recordError).toHaveBeenCalledTimes(1);
    expect(recordError).toHaveBeenCalledWith("HTTP 422 x");
    (recordError as jest.Mock).mockClear();
    browserErrorText(error);
    expect(recordError).not.toHaveBeenCalled();
  });
});

describe("errorText (phone) for other errors", () => {
  beforeEach(() => (recordError as jest.Mock).mockClear());

  it.each<[string, unknown, StringKey, boolean, string]>([
    ["storage full", new Error("database or disk is full"), "phoneStorageFull", false, "Error database or disk is full"],
    ["session revoked, kept", new SessionRevokedError(true), "accessRemovedKept", false, "SessionRevokedError session_revoked"],
    ["session revoked", new SessionRevokedError(false), "sessionRevoked", false, "SessionRevokedError session_revoked"],
    ["sign in required", new SignInRequiredError(), "signInAgain", false, "SignInRequiredError sign_in_required"],
    ["already enrolled", new AlreadyEnrolledError(), "errAlreadyEnrolled", false, "AlreadyEnrolledError already_enrolled"],
    ["store collision", new AccountStoreCollisionError(), "accountStoreCollision", false, "AccountStoreCollisionError account_store_collision"],
    ["not in slot", new NotInSlotError(), "errSlotChanged", false, "NotInSlotError not_in_slot"],
    ["workspace stale", new Error("workspace_stale"), "workspaceStale", false, "Error workspace_stale"],
    ["TypeError", new TypeError("Network request failed"), "errNetwork", false, "network"],
    ["offline", new OfflineError(), "errNetwork", false, "offline"],
    ["code-bug TypeError", new TypeError("Cannot read properties of undefined (reading 'x')"), G, true, "TypeError Cannot read properties of undefined (reading 'x')"],
    ["plain Error", new Error("boom"), G, true, "Error boom"],
    ["string", "boom", G, true, "unknown"],
    ["undefined", undefined, G, true, "unknown"],
  ])("%s", (_name, error, key, withRef, filed) => {
    expectKey(errorText(error), key, withRef);
    expect(recordError).toHaveBeenCalledTimes(1);
    expect(recordError).toHaveBeenCalledWith(filed);
  });
});

describe("browserErrorText (web) for other errors", () => {
  it.each<[string, unknown, StringKey, boolean]>([
    ["TypeError", new TypeError("Failed to fetch"), "errNetwork", false],
    ["offline", new OfflineError(), "errNetwork", false],
    ["Chrome body read died", new TypeError("network error"), "errNetwork", false],
    ["RN request timed out", new TypeError("Network request timed out"), "errNetwork", false],
    ["Safari connection lost", new TypeError("The network connection was lost."), "errNetwork", false],
    ["Safari offline", new TypeError("The Internet connection appears to be offline."), "errNetwork", false],
    ["code-bug TypeError", new TypeError("Cannot read properties of undefined (reading 'x')"), "serverError", true],
    ["plain Error", new Error("boom"), "serverError", true],
    ["session revoked", new SessionRevokedError(true), "serverError", true],
    ["workspace stale", new Error("workspace_stale"), "serverError", true],
    ["storage full", new Error("database or disk is full"), "serverError", true],
    ["string", "boom", "serverError", true],
  ])("%s", (_name, error, key, withRef) => {
    expectKey(browserErrorText(error), key, withRef);
  });
});

describe("revision messages", () => {
  const ATTENTION: Array<[string | null, StringKey]> = [
    ["revision_locked", "revisionLocked"],
    ["case_already_submitted", "revisionAlreadySubmitted"],
    ["case_closed", "revisionCaseClosed"],
    ["case_state_conflict", "revisionCaseConflict"],
    ["invalid_reason", "revisionInvalidReason"],
    ["required_finish_partial", "revisionInvalidReason"],
    ["not_found", "revisionUnavailable"],
    ["invalid_definition_pin", "revisionPinInvalid"],
    ["answers_hash_invalid", "revisionRetry"],
    ["local_hash_mismatch", "revisionRetry"],
    ["invalid_revision_snapshot", "revisionRetry"],
    ["invalid_revision_ack", "revisionRetry"],
    ["unheard_of", "revisionRetry"],
    [null, "revisionRetry"],
  ];
  it.each(ATTENTION)("attentionMessage(%s)", (code, key) => expect(attentionMessage(code)).toBe(t(key)));

  const row = (refusal_code: string | null, state: string) => ({ refusal_code, state }) as never;
  it.each<[string | null, string, StringKey]>([
    ["revision_locked", "ready", "revisionLocked"],
    ["case_already_submitted", "attention", "revisionAlreadySubmitted"],
    ["case_closed", "draft", "revisionCaseClosed"],
    ["case_state_conflict", "ready", "revisionCaseConflict"],
    ["invalid_reason", "ready", "revisionInvalidReason"],
    ["required_finish_partial", "ready", "revisionInvalidReason"],
    ["not_found", "ready", "revisionUnavailable"],
    ["invalid_definition_pin", "ready", "revisionSaved"],
    ["invalid_definition_pin", "attention", "revisionRetry"],
    ["answers_hash_invalid", "draft", "draftInProgress"],
    [null, "ready", "revisionSaved"],
    [null, "attention", "revisionRetry"],
    [null, "draft", "draftInProgress"],
  ])("localRevisionStatus(%s, %s)", (code, state, key) => expect(localRevisionStatus(row(code, state))).toBe(t(key)));

  describe("loadFailureMessage", () => {
    beforeEach(() => (recordError as jest.Mock).mockClear());
    it("incompatible engine is a fixed English string, nothing recorded", () => {
      expect(loadFailureMessage(new FormDefinitionError("incompatible_engine"))).toBe(
        "Update the app to open this form. Your saved answers remain on this device.",
      );
      expect(recordError).not.toHaveBeenCalled();
    });
    it("unknown saved definition is a fixed English string", () => {
      expect(loadFailureMessage(new PinnedDefinitionError("unknown_saved_definition"))).toBe(
        "This interview's original form is unavailable. Your saved answers remain on this device.",
      );
    });
    it("revision_project_unavailable", () => {
      expect(loadFailureMessage(new Error("revision_project_unavailable"))).toBe(t("revisionUnavailable"));
      expect(recordError).not.toHaveBeenCalled();
    });
    it.each<[string, number, StringKey]>([
      ["revision_locked", 409, "revisionLocked"],
      ["case_already_submitted", 409, "revisionAlreadySubmitted"],
      ["case_closed", 409, "revisionCaseClosed"],
      ["case_state_conflict", 409, "revisionCaseConflict"],
      ["whatever", 404, "revisionUnavailable"],
    ])("ApiError %s / %s", (code, status, key) => {
      expect(loadFailureMessage(new ApiError(status, code))).toBe(t(key));
      expect(recordError).not.toHaveBeenCalled();
    });
    it("session errors use the phone text", () => {
      expect(loadFailureMessage(new SessionRevokedError(true))).toBe(t("accessRemovedKept"));
      expect(loadFailureMessage(new SignInRequiredError())).toBe(t("signInAgain"));
      expect(recordError).toHaveBeenCalledTimes(2);
    });
    it("anything else: the retry text over the phone's last line", () => {
      for (const error of [new ApiError(500, "x"), new Error("boom"), new ApiError(405, undefined)]) {
        const text = loadFailureMessage(error);
        expect(text.startsWith(`${t("revisionRetry")}\n`)).toBe(true);
        expect(text.split("\n")).toHaveLength(2);
        expect(text.split("\n")[1]).toMatch(/^Ref: /);
      }
      // A TypeError and a storage-full error have no Ref line, so the retry text sits over their own text.
      expect(loadFailureMessage(new TypeError("Network request failed"))).toBe(`${t("revisionRetry")}\n${t("errNetwork")}`);
      expect(loadFailureMessage(new Error("disk is full"))).toBe(`${t("revisionRetry")}\n${t("phoneStorageFull")}`);
      expect(recordError).toHaveBeenCalledTimes(5);
    });
  });
});
