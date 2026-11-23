import { ApiError } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./auth";

/** 403 codes that gate the whole account rather than one project's rows. */
export const ACCOUNT_GATE_CODES = new Set(["terms_required", "password_change_required", "maintenance", "no_collection_access"]);

/** An account-wide 403: every project's upload would be refused the same way. */
export const isAccountGate = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 403 && ACCOUNT_GATE_CODES.has(error.code ?? "");

/**
 * Whether an upload failure must stop the whole run (everything kept): a
 * revoked or missing session, an account-wide 403, or anything that is not an
 * API reply (network). A per-project 403 is not fatal; it refuses that row only.
 */
export const isFatalUploadError = (error: unknown): boolean =>
  error instanceof SessionRevokedError || error instanceof SignInRequiredError ||
  !(error instanceof ApiError) || isAccountGate(error);
