/**
 * Device enrolment record, interviewer accounts and their tokens, all in
 * Keystore-backed SecureStore, plus authenticated calls with refresh-token
 * rotation (pattern from vendor/who-va-2022/examples/expo-demo/components/AuthSession.ts).
 *
 * Wipe rules (docs/policy/field-data-collection.md, Path B): only
 * `401 session_revoked` (admin or device revoke, grant withdrawn) wipes, and
 * it wipes that interviewer's store and tokens only. `session_ended`
 * (password reset, account deactivated, project closed) keeps the data.
 * Every other refusal of a refresh (`refresh_reused`, `409
 * refresh_retry_race`, `session_expired`, `refresh_invalid`,
 * `device_invalid`) drops the dead tokens and marks the account "sign in
 * again", keeping its data; offline and 5xx keep everything. Unsent
 * interviews wait for the next sign-in.
 */
import * as SecureStore from "expo-secure-store";

import { ApiError, DEVICE_API, requestJson } from "./api";
import { deleteInterviewerDb } from "./interviewerDb";

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
}

interface Tokens {
  access_token: string;
  access_expires_at: string;
  refresh_token: string;
  refresh_expires_at: string;
}

export class SessionRevokedError extends Error {
  constructor() {
    super("session_revoked");
    this.name = "SessionRevokedError";
  }
}

/** The refresh token was refused for a reason other than revocation: sign in again, keep the data. */
export class SignInRequiredError extends Error {
  constructor() {
    super("sign_in_required");
    this.name = "SignInRequiredError";
  }
}

const DEVICE_KEY = "device";
const DEVICE_SECRET_KEY = "device_secret";
const ACCOUNTS_KEY = "accounts";
const tokensKey = (userId: string) => `tokens.${userId}`;
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY
};

async function readJson<T>(key: string): Promise<T | undefined> {
  const raw = await SecureStore.getItemAsync(key, OPTIONS);
  if (!raw) return undefined;
  try {
    return JSON.parse(raw) as T;
  } catch {
    return undefined;
  }
}

const writeJson = (key: string, value: unknown) => SecureStore.setItemAsync(key, JSON.stringify(value), OPTIONS);

export const loadDevice = () => readJson<Device>(DEVICE_KEY);
const loadDeviceSecret = () => SecureStore.getItemAsync(DEVICE_SECRET_KEY, OPTIONS);
export const loadAccounts = async () => (await readJson<Account[]>(ACCOUNTS_KEY)) ?? [];

/** POST /enroll and keep the device record. The secret is stored apart and sent only to /sessions. */
export async function enrolDevice(
  server: string,
  code: string,
  deviceName: string,
  appVersion: string
): Promise<Device> {
  const { body } = await requestJson<{
    device_id: string;
    device_secret: string;
    project: { project_id: string; name: string };
  }>(server, `${DEVICE_API}/enroll`, {
    method: "POST",
    body: { code, device_name: deviceName, platform: "android", app_version: appVersion }
  });
  const device: Device = {
    device_id: body.device_id,
    server,
    project_id: body.project.project_id,
    project_name: body.project.name
  };
  await SecureStore.setItemAsync(DEVICE_SECRET_KEY, body.device_secret, OPTIONS);
  await writeJson(DEVICE_KEY, device);
  return device;
}

/** Drop the enrolment (used when the server says the device is revoked). Interviewer stores are untouched. */
export async function forgetDevice(): Promise<void> {
  await SecureStore.deleteItemAsync(DEVICE_SECRET_KEY, OPTIONS);
  await SecureStore.deleteItemAsync(DEVICE_KEY, OPTIONS);
}

/** POST /sessions; throws ApiError (401 second_factor_required, 403 no_interviewer_grant, ...). */
export async function signIn(email: string, password: string, otp?: string): Promise<Account> {
  const device = await loadDevice();
  const secret = await loadDeviceSecret();
  if (!device || !secret) throw new Error("not_enrolled");
  const { body } = await requestJson<Tokens & { user: { user_id: string; name: string } }>(
    device.server,
    `${DEVICE_API}/sessions`,
    {
      method: "POST",
      body: { device_id: device.device_id, device_secret: secret, email, password, ...(otp ? { otp } : {}) }
    }
  );
  const account: Account = { user_id: String(body.user.user_id), name: body.user.name };
  await saveTokens(account.user_id, body);
  const others = (await loadAccounts()).filter((a) => a.user_id !== account.user_id);
  await writeJson(ACCOUNTS_KEY, [...others, account]);
  return account;
}

function saveTokens(userId: string, t: Tokens): Promise<void> {
  const tokens: Tokens = {
    access_token: t.access_token,
    access_expires_at: t.access_expires_at,
    refresh_token: t.refresh_token,
    refresh_expires_at: t.refresh_expires_at
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
    accounts.map((a) => (a.user_id === userId ? { ...a, needs_sign_in: true } : a))
  );
}

/** Sign out: tell the server (best effort, offline is fine), then wipe. */
export async function signOut(userId: string): Promise<void> {
  try {
    await authedRequest(userId, `${DEVICE_API}/sessions/current`, { method: "DELETE" });
  } catch {
    // Offline or already revoked: the local wipe still happens.
  }
  await wipeInterviewer(userId);
}

// One refresh in flight per interviewer. Two concurrent 401s must not both
// spend the same refresh token: reuse of a rotated token revokes the session.
const refreshing = new Map<string, Promise<Tokens>>();

function refresh(userId: string, server: string): Promise<Tokens> {
  let pending = refreshing.get(userId);
  if (!pending) {
    pending = doRefresh(userId, server).finally(() => refreshing.delete(userId));
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
    const { body } = await requestJson<Tokens>(server, `${DEVICE_API}/sessions/refresh`, {
      method: "POST",
      body: { refresh_token: current.refresh_token, device_id: device?.device_id, device_secret: secret }
    });
    await saveTokens(userId, body);
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
export async function classifyAuthError(userId: string, error: unknown): Promise<unknown> {
  if (!(error instanceof ApiError)) return error;
  if (error.status === 401 && error.code === "session_revoked") {
    await wipeInterviewer(userId);
    return new SessionRevokedError();
  }
  if (error.status === 401 || (error.status === 409 && error.code === "refresh_retry_race")) {
    await markSignInRequired(userId);
    return new SignInRequiredError();
  }
  return error;
}

/**
 * An authenticated device-API call for one interviewer. On 401 it refreshes
 * once (or picks up tokens another call already rotated) and retries once.
 * Throws SessionRevokedError (store already wiped), SignInRequiredError,
 * ApiError, or the network error.
 */
export async function authedRequest<T>(
  userId: string,
  path: string,
  init: { method?: string; body?: unknown } = {}
): Promise<{ status: number; body: T }> {
  const device = await loadDevice();
  const tokens = await readJson<Tokens>(tokensKey(userId));
  if (!device) throw new Error("not_enrolled");
  if (!tokens) throw new SignInRequiredError();
  try {
    return await requestJson<T>(device.server, path, { ...init, token: tokens.access_token });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw error;
    if (error.code === "session_revoked") throw await classifyAuthError(userId, error);
  }
  const latest = await readJson<Tokens>(tokensKey(userId));
  const next =
    latest && latest.access_token !== tokens.access_token ? latest : await refresh(userId, device.server);
  try {
    return await requestJson<T>(device.server, path, { ...init, token: next.access_token });
  } catch (error) {
    throw await classifyAuthError(userId, error);
  }
}
