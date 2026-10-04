/**
 * Device enrolment record, interviewer accounts and their tokens, all in
 * Keystore-backed SecureStore, plus authenticated calls with refresh-token
 * rotation (pattern from vendor/who-va-2022/examples/expo-demo/components/AuthSession.ts).
 *
 * Wipe rules (docs/policy/field-data-collection.md, Path B): only
 * `401 session_revoked` (admin or device revoke, grant withdrawn) wipes, and
 * it wipes that interviewer's store and tokens only. `session_ended`
 * (password reset or account deactivated) keeps the data. Losing the last
 * active project is session_revoked; losing one project is handled by access refresh.
 * Every other refusal of a refresh (`refresh_reused`, `409
 * refresh_retry_race`, `session_expired`, `refresh_invalid`,
 * `device_invalid`) drops the dead tokens and marks the account "sign in
 * again", keeping its data; offline and 5xx keep everything. Unsent
 * interviews wait for the next sign-in. A wipe (sign-out, `session_revoked`,
 * five wrong PINs) removes the database file, its store secret, PIN
 * counter and biometric entry, the tokens and the account entry.
 */
import * as SecureStore from "expo-secure-store";

import { ApiError, AUTH_API, parseAccessSummary, requestJson, type AccessSummary } from "./api";
import { SessionRevokedError, SignInRequiredError } from "./authErrors";
import {
  deleteInterviewerDb,
  unlockInterviewerDb,
  type UnlockResult,
} from "./interviewerDb";

export { SessionRevokedError, SignInRequiredError } from "./authErrors";

export interface Device {
  device_id: string;
  server: string;
  project_id: string;
  project_name: string;
}

/** Display name only: the home screen never shows anything else about an account. */
export interface Account {
  user_id: string;
  name: string;
  /** The server refused the refresh token without revoking: sign in again, data kept. */
  needs_sign_in?: boolean;
  terms_required?: boolean;
  /** A global bearer gate keeps local work but blocks collection until fixed. */
  access_blocked?: "factor_setup_required" | "maintenance";
}

interface Tokens {
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
  terms_required?: boolean;
}

const DEVICE_KEY = "device";
const DEVICE_SECRET_KEY = "device_secret";
const ACCOUNTS_KEY = "accounts";
const tokensKey = (userId: string) => `tokens.${userId}`;
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

const termsListeners = new Set<() => void>();
const accountListeners = new Set<() => void>();
const accessListeners = new Set<(userId: string, access: AccessSummary) => Promise<void> | void>();
const accessRefreshes = new Map<string, Promise<AccessSummary | undefined>>();
/** Notify the native provider when a bearer response changes the terms gate. */
export function subscribeTermsChanges(listener: () => void): () => void {
  termsListeners.add(listener);
  return () => {
    termsListeners.delete(listener);
  };
}

/** Notify native screens when account gates or the authoritative access summary changes. */
export function subscribeAccountChanges(listener: () => void): () => void {
  accountListeners.add(listener);
  return () => accountListeners.delete(listener);
}

/** Reconcile encrypted native reference state after a successful access refresh. */
export function subscribeAccessChanges(
  listener: (userId: string, access: AccessSummary) => Promise<void> | void,
): () => void {
  accessListeners.add(listener);
  return () => accessListeners.delete(listener);
}

async function readJson<T>(key: string): Promise<T | undefined> {
  const raw = await SecureStore.getItemAsync(key, OPTIONS);
  if (!raw) return undefined;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return undefined;
  }
}

const writeJson = (key: string, value: unknown) =>
  SecureStore.setItemAsync(key, JSON.stringify(value), OPTIONS);

export const loadDevice = () => readJson<Device>(DEVICE_KEY);
const loadDeviceSecret = () =>
  SecureStore.getItemAsync(DEVICE_SECRET_KEY, OPTIONS);
export const loadAccounts = async () =>
  (await readJson<Account[]>(ACCOUNTS_KEY)) ?? [];

/** Refresh the grant summary without recursively refreshing the access token. */
export function refreshAccessSummary(userId: string): Promise<AccessSummary | undefined> {
  const existing = accessRefreshes.get(userId);
  if (existing) return existing;
  const pending = refreshAccessSummaryOnce(userId).finally(() => {
    if (accessRefreshes.get(userId) === pending) accessRefreshes.delete(userId);
  });
  accessRefreshes.set(userId, pending);
  return pending;
}

async function refreshAccessSummaryOnce(userId: string): Promise<AccessSummary | undefined> {
  const device = await loadDevice();
  const tokens = await readJson<Tokens>(tokensKey(userId));
  if (!device || !tokens) return undefined;
  try {
    const { body } = await requestJson<unknown>(device.server, "/api/v1/me/access", {
      token: tokens.access_token,
    });
    return await publishAccessSummary(userId, body);
  } catch (error) {
    // An access refresh is auxiliary to sign-in/refresh. Preserve the session
    // when the device is offline or the terms gate is still open; the next
    // authenticated call will retry after terms acceptance.
    if (error instanceof TypeError) return undefined;
    if (error instanceof ApiError && error.status === 403 && error.code === "terms_required") {
      await setTermsRequired(userId, true);
      return undefined;
    }
    if (error instanceof ApiError && error.status === 403 && isGlobalAccessGate(error.code)) {
      await setAccessBlocked(userId, error.code);
    }
    if (error instanceof ApiError && error.status === 401) {
      throw await classifyAuthError(userId, error);
    }
    throw error;
  }
}

async function publishAccessSummary(userId: string, value: unknown): Promise<AccessSummary> {
  const access = parseAccessSummary(value);
  await setAccessBlocked(userId, undefined);
  for (const listener of accessListeners) await listener(userId, access);
  return access;
}

function isGlobalAccessGate(code: string | undefined): code is "factor_setup_required" | "maintenance" {
  return code === "factor_setup_required" || code === "maintenance";
}

/** POST /enroll and keep the device record. The secret is stored apart and sent only to /sessions. */
export async function enrolDevice(
  server: string,
  code: string,
  deviceName: string,
  appVersion: string,
): Promise<Device> {
  const { body } = await requestJson<{
    device_id: string;
    device_secret: string;
    project: { project_id: string; name: string };
  }>(server, `${AUTH_API}/enroll`, {
    method: "POST",
    body: {
      code,
      device_name: deviceName,
      platform: "android",
      app_version: appVersion,
    },
  });
  const device: Device = {
    device_id: body.device_id,
    server,
    project_id: body.project.project_id,
    project_name: body.project.name,
  };
  await SecureStore.setItemAsync(
    DEVICE_SECRET_KEY,
    body.device_secret,
    OPTIONS,
  );
  await writeJson(DEVICE_KEY, device);
  return device;
}

/** Drop the enrolment (used when the server says the device is revoked). Interviewer stores are untouched. */
export async function forgetDevice(): Promise<void> {
  await SecureStore.deleteItemAsync(DEVICE_SECRET_KEY, OPTIONS);
  await SecureStore.deleteItemAsync(DEVICE_KEY, OPTIONS);
}

/** POST /sessions with an email or canonical +91 mobile identifier; throws ApiError. */
export async function signIn(
  identifier: string,
  password: string,
  otp?: string,
): Promise<Account> {
  const device = await loadDevice();
  const secret = await loadDeviceSecret();
  if (!device || !secret) throw new Error("not_enrolled");
  const { body } = await requestJson<
    Tokens & { user: { user_id: string; name: string; email?: string | null }; access: unknown }
  >(device.server, `${AUTH_API}/sessions`, {
    method: "POST",
    // The device API keeps `email` as its backwards-compatible field name;
    // it accepts an email or the canonical +91 mobile identifier.
    body: {
      device_id: device.device_id,
      device_secret: secret,
      email: identifier,
      password,
      ...(otp ? { otp } : {}),
    },
  });
  const account: Account = {
    user_id: String(body.user.user_id),
    name: body.user.name,
    ...(body.terms_required ? { terms_required: true } : {}),
  };
  await saveTokens(account.user_id, body);
  const others = (await loadAccounts()).filter(
    (a) => a.user_id !== account.user_id,
  );
  await writeJson(ACCOUNTS_KEY, [...others, account]);
  await publishAccessSummary(account.user_id, body.access);
  return account;
}

function saveTokens(userId: string, t: Tokens): Promise<void> {
  const tokens: Tokens = {
    access_token: t.access_token,
    access_expires_at: t.access_expires_at,
    refresh_token: t.refresh_token,
    refresh_expires_at: t.refresh_expires_at,
  };
  return writeJson(tokensKey(userId), tokens);
}

/** Wipe one interviewer: database, tokens, account entry. Nobody else's. */
export async function wipeInterviewer(userId: string): Promise<void> {
  await deleteInterviewerDb(userId);
  await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
  const remaining = (await loadAccounts()).filter((a) => a.user_id !== userId);
  await writeJson(ACCOUNTS_KEY, remaining);
}

/** The server refused this interviewer's refresh without revoking: drop the dead tokens, flag the account, keep its data. */
async function markSignInRequired(userId: string): Promise<void> {
  await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
  const accounts = await loadAccounts();
  await writeJson(
    ACCOUNTS_KEY,
    accounts.map((a) =>
      a.user_id === userId ? { ...a, needs_sign_in: true } : a,
    ),
  );
}

/** Sign out: tell the server (best effort, offline is fine), then wipe. */
export async function signOut(userId: string): Promise<void> {
  try {
    await authedRequest(userId, `${AUTH_API}/sessions/current`, {
      method: "DELETE",
    });
  } catch {
    // Offline or already revoked: the local wipe still happens.
  }
  await wipeInterviewer(userId);
}

/**
 * Try the interviewer's PIN. After the fifth wrong PIN in a row their store
 * and keys are already deleted (src/interviewerDb.ts); this then ends the
 * server session (best effort) and drops their tokens and account entry.
 * Nobody else's data is touched.
 */
export async function unlockInterviewer(
  userId: string,
  pin: string,
): Promise<UnlockResult> {
  const result = await unlockInterviewerDb(userId, pin);
  if (!result.ok && result.wipe) await signOut(userId);
  return result;
}

// One refresh in flight per interviewer. Two concurrent 401s must not both
// spend the same refresh token: reuse of a rotated token revokes the session.
const refreshing = new Map<string, Promise<Tokens>>();

function refresh(userId: string, server: string): Promise<Tokens> {
  let pending = refreshing.get(userId);
  if (!pending) {
    pending = doRefresh(userId, server).finally(() =>
      refreshing.delete(userId),
    );
    refreshing.set(userId, pending);
  }
  return pending;
}

async function doRefresh(userId: string, server: string): Promise<Tokens> {
  const current = await readJson<Tokens>(tokensKey(userId));
  if (!current) throw new SignInRequiredError();
  const device = await loadDevice();
  const secret = await loadDeviceSecret();
  try {
    const { body } = await requestJson<Tokens & { access: unknown }>(
      server,
      `${AUTH_API}/sessions/refresh`,
      {
        method: "POST",
        body: {
          refresh_token: current.refresh_token,
          device_id: device?.device_id,
          device_secret: secret,
        },
      },
    );
    await saveTokens(userId, body);
    await setTermsRequired(userId, body.terms_required === true);
    await publishAccessSummary(userId, body.access);
    return body;
  } catch (error) {
    throw await classifyAuthError(userId, error);
  }
}

/**
 * Map a refused call to what the app does. Only `session_revoked` wipes;
 * any other 401, and 409 `refresh_retry_race` (the server rotated but the
 * response was lost), means "sign in again" with the data kept.
 */
export async function classifyAuthError(
  userId: string,
  error: unknown,
): Promise<unknown> {
  if (!(error instanceof ApiError)) return error;
  if (error.status === 403 && error.code === "terms_required") {
    await setTermsRequired(userId, true);
    return error;
  }
  if (error.status === 403) {
    if (isGlobalAccessGate(error.code)) await setAccessBlocked(userId, error.code);
    // Grants can change while the app is open. Reconcile before returning so
    // mounted native screens cannot continue using stale scope.
    await refreshAccessSummary(userId);
  }
  if (error.status === 401 && error.code === "session_revoked") {
    await wipeInterviewer(userId);
    return new SessionRevokedError();
  }
  if (
    error.status === 401 ||
    (error.status === 409 && error.code === "refresh_retry_race")
  ) {
    await markSignInRequired(userId);
    return new SignInRequiredError();
  }
  return error;
}

/**
 * An authenticated API call for one interviewer. On 401 it refreshes
 * once (or picks up tokens another call already rotated) and retries once.
 * A bodyFactory creates a fresh body for each HTTP attempt.
 * Throws SessionRevokedError (store already wiped), SignInRequiredError,
 * ApiError, or the network error.
 */
export async function authedRequest<T>(
  userId: string,
  path: string,
  init: {
    method?: string;
    body?: unknown;
    bodyFactory?: () => unknown;
    timeoutMs?: number;
  } = {},
): Promise<{ status: number; body: T }> {
  const device = await loadDevice();
  const tokens = await readJson<Tokens>(tokensKey(userId));
  if (!device) throw new Error("not_enrolled");
  if (!tokens) throw new SignInRequiredError();
  const { bodyFactory, ...requestInit } = init;
  const initialBody = bodyFactory ? bodyFactory() : requestInit.body;
  try {
    return await requestJson<T>(device.server, path, {
      ...requestInit,
      body: initialBody,
      token: tokens.access_token,
    });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401)
      throw await classifyAuthError(userId, error);
    if (error.code === "session_revoked")
      throw await classifyAuthError(userId, error);
  }
  const latest = await readJson<Tokens>(tokensKey(userId));
  const next =
    latest && latest.access_token !== tokens.access_token
      ? latest
      : await refresh(userId, device.server);
  const retryBody = bodyFactory ? bodyFactory() : requestInit.body;
  try {
    return await requestJson<T>(device.server, path, {
      ...requestInit,
      body: retryBody,
      token: next.access_token,
    });
  } catch (error) {
    throw await classifyAuthError(userId, error);
  }
}

async function setTermsRequired(
  userId: string,
  required: boolean,
): Promise<void> {
  const accounts = await loadAccounts();
  if (
    !accounts.some(
      (account) =>
        account.user_id === userId &&
        (account.terms_required === true) !== required,
    )
  )
    return;
  await writeJson(
    ACCOUNTS_KEY,
    accounts.map((account) => {
      if (account.user_id !== userId) return account;
      const { terms_required: _previous, ...rest } = account;
      return required ? { ...rest, terms_required: true } : rest;
    }),
  );
  for (const listener of termsListeners) listener();
  for (const listener of accountListeners) listener();
}

async function setAccessBlocked(
  userId: string,
  blocked: "factor_setup_required" | "maintenance" | undefined,
): Promise<void> {
  const accounts = await loadAccounts();
  let changed = false;
  const next = accounts.map((account) => {
    if (account.user_id !== userId || account.access_blocked === blocked) return account;
    changed = true;
    if (!blocked) {
      const { access_blocked: _blocked, ...rest } = account;
      return rest;
    }
    return { ...account, access_blocked: blocked };
  });
  if (!changed) return;
  await writeJson(ACCOUNTS_KEY, next);
  for (const listener of accountListeners) listener();
}

/** Acceptance uses the device session and never wipes unsent work. */
export async function acceptDeviceTerms(userId: string): Promise<void> {
  await authedRequest(userId, "/api/v1/me/terms", {
    method: "POST",
    body: { accept_terms: true },
  });
  await setTermsRequired(userId, false);
}
