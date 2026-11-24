import { ErrorCode } from "./errorCodes";
import type { StringKey } from "./i18n";

/**
 * The one table from a server error (machine code, HTTP status) to a UI string key. Pure: no i18n lookup, no
 * logging, no Ref line; the platform adapters (errorText in ui.tsx, browserErrorText in web/common.tsx) turn the
 * key into text and file the error.
 *
 * The phone and the browser map the same reply differently on purpose of history, not of design (a 429 or a
 * maintenance reply is its own text on the phone and the generic server error on the web; a 422 is the generic
 * error on the phone and the validation text on the web). They are kept apart here, each as today; whether to
 * unify them is the owner's call, not this module's.
 */
export type ErrorPlatform = "phone" | "web";

export interface ErrorMessageKey {
  key: StringKey;
  /** True when the text is followed by the support Ref line. */
  ref: boolean;
}

/** Phone: a machine code with a fixed text whatever the status. */
const PHONE_CODE_KEYS = new Map<string, StringKey>([
  [ErrorCode.DEVICE_LIMIT, "deviceLimit"],
  [ErrorCode.ENROLMENT_INVALID, "errEnrolInvalid"],
  [ErrorCode.CSRF_FAILED, "csrfRefreshed"],
  [ErrorCode.COOKIE_SESSION_REQUIRED, "loginRequiredAction"],
  [ErrorCode.MAINTENANCE, "serverUnavailable"],
  // Training session types (docs/policy/training-session-types.md); before the generic forbidden.
  [ErrorCode.NOT_IN_YOUR_TRAINING_SET, "errNotInTrainingSet"],
  [ErrorCode.ROLE_NOT_IN_SESSION_TYPE, "errRoleNotInSessionType"],
  [ErrorCode.CORPUS_MISSING, "errCorpusMissing"],
  [ErrorCode.CORPUS_CASES_INELIGIBLE, "errCorpusMissing"],
  [ErrorCode.APP_UPDATE_REQUIRED, "errAppUpdateRequired"],
  [ErrorCode.FORBIDDEN, "serverForbidden"],
  [ErrorCode.PROJECT_FORBIDDEN, "serverForbidden"],
  [ErrorCode.PASSWORD_CHANGE_REQUIRED, "termsRequired"],
  [ErrorCode.TERMS_REQUIRED, "termsRequired"],
  // A mobile-only account until a sign-in code is redeemed, or an email not yet verified.
  [ErrorCode.EMAIL_UNVERIFIED, "errAccountNotActivated"],
  [ErrorCode.NO_INTERVIEWER_GRANT, "errNoGrant"],
  [ErrorCode.PROJECT_INTAKE_OFF, "errProjectIntakeOff"],
  [ErrorCode.NO_COLLECTION_ACCESS, "noCollectionAccess"],
  [ErrorCode.DEVICE_REVOKED, "errDeviceRevoked"],
  [ErrorCode.DEMO_LIMIT, "demoLimit"],
  [ErrorCode.CAP_REACHED, "demoFull"],
]);

function phoneKeyFor(code: string | undefined, status: number): ErrorMessageKey {
  // A proxy's maintenance page is HTML, which the client reports as redirected_response.
  if (code === ErrorCode.REDIRECTED_RESPONSE && [502, 503, 504].includes(status)) return { key: "serverUnavailable", ref: false };
  const key = code === undefined ? undefined : PHONE_CODE_KEYS.get(code);
  if (key) return { key, ref: false };
  if (status === 429) return { key: "errRateLimited", ref: false };
  if (status === 401) return { key: "errSignIn", ref: false };
  return { key: "errGeneric", ref: true };
}

function webKeyFor(code: string | undefined, status: number): ErrorMessageKey {
  if (code === ErrorCode.UNAUTHORIZED || status === 401) return { key: "serverUnauthorized", ref: false };
  if (code === ErrorCode.TERMS_REQUIRED) return { key: "loginRequiredAction", ref: false };
  if (status === 403) return { key: "serverForbidden", ref: false };
  if (code === ErrorCode.CSRF_FAILED) return { key: "csrfRefreshed", ref: false };
  if (status === 422 || status === 400) return { key: "serverValidation", ref: true };
  if (status >= 500) return { key: "serverUnavailable", ref: true };
  return { key: "serverError", ref: true };
}

/** The string key (and whether a Ref line follows) a server error shows as on `platform`. */
export function errorKeyFor({ code, status, platform }: { code: string | undefined; status: number; platform: ErrorPlatform }): ErrorMessageKey {
  return platform === "phone" ? phoneKeyFor(code, status) : webKeyFor(code, status);
}

/** The refusals the server gives a revision upload or open when the case moved on. */
const REVISION_CONFLICT_KEYS = new Map<string, StringKey>([
  [ErrorCode.REVISION_LOCKED, "revisionLocked"],
  [ErrorCode.CASE_ALREADY_SUBMITTED, "revisionAlreadySubmitted"],
  [ErrorCode.CASE_CLOSED, "revisionCaseClosed"],
  [ErrorCode.CASE_STATE_CONFLICT, "revisionCaseConflict"],
]);

/** Every refusal code a revision row can carry that has a text of its own (the conflicts plus these). */
const REVISION_REFUSAL_KEYS = new Map<string, StringKey>([
  ...REVISION_CONFLICT_KEYS,
  ["invalid_reason", "revisionInvalidReason"],
  ["required_finish_partial", "revisionInvalidReason"],
  ["not_found", "revisionUnavailable"],
]);

/** The text of a stored revision refusal code, if it has one of its own. */
export function revisionRefusalKey(code: string | null | undefined): StringKey | undefined {
  return code == null ? undefined : REVISION_REFUSAL_KEYS.get(code);
}

/** The text of a failed revision open for an ApiError: the four conflicts by code, any 404 as unavailable. */
export function revisionOpenKey(code: string | undefined, status: number): StringKey | undefined {
  const conflict = code === undefined ? undefined : REVISION_CONFLICT_KEYS.get(code);
  if (conflict) return conflict;
  return status === 404 ? "revisionUnavailable" : undefined;
}
