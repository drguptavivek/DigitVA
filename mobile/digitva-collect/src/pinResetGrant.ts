/**
 * One-use permission to reset a forgotten PIN (digitva-kfi), held in memory only. src/auth.ts signIn grants it
 * only when asked ({forPinReset}, from the "Forgot PIN?" sign-in) and for the user id the server's reply names, so an
 * ordinary or other-account sign-in never allows a reset; src/interviewerDb.ts resetInterviewerPin takes it. Its own module so test mocks of auth or
 * interviewerDb do not need to know about it.
 */

/** How long a password sign-in allows a PIN reset for that account. */
export const PIN_RESET_WINDOW_MS = 5 * 60_000;
const grants = new Map<string, number>();

export function allowPinReset(userId: string, now = Date.now()): void {
  grants.set(userId, now + PIN_RESET_WINDOW_MS);
}

/** Drop one account's grant, or every grant: on unlock, on lock and when the reset flow is left. */
export function clearPinResetGrant(userId?: string): void {
  if (userId === undefined) grants.clear();
  else grants.delete(userId);
}

/** True while the grant is unexpired. Does not use it up; an expired one is dropped. */
export function hasPinResetGrant(userId: string, now = Date.now()): boolean {
  const until = grants.get(userId);
  if (until !== undefined && now > until) grants.delete(userId);
  return until !== undefined && now <= until;
}

/** True once per grant, within the window; any call uses the grant up. */
export function takePinResetGrant(userId: string, now = Date.now()): boolean {
  const valid = hasPinResetGrant(userId, now);
  grants.delete(userId);
  return valid;
}
