/**
 * Device enrolment record, interviewer accounts and their tokens, all in
 * Keystore-backed SecureStore, plus authenticated calls with refresh-token
 * rotation (pattern from vendor/who-va-2022/examples/expo-demo/components/AuthSession.ts).
 *
 * Wipe rules (docs/policy/field-data-collection.md, Path B): only
 * `401 session_revoked` (admin or device revoke, grant withdrawn) wipes, and
 * it wipes that interviewer's store and tokens only, and only when the
 * unlocked store holds no unsent work. With unsent work, or while the store
 * is locked (its contents cannot be counted), the tokens are dropped and the
 * account is marked `access_removed`: read-only, its encrypted store kept
 * until the interviewer signs in again or a later unlock finds nothing
 * unsent (owner decision 2026-10-22). `session_ended`
 * (password reset or account deactivated) keeps the data. Losing the last
 * active project is session_revoked; losing one project is handled by access refresh.
 * Every other refusal of a refresh (`refresh_reused`, `409
 * refresh_retry_race`, `session_expired`, `refresh_invalid`,
 * `device_invalid`) drops the dead tokens and marks the account "sign in
 * again", keeping its data; offline and 5xx keep everything. Unsent
 * interviews wait for the next sign-in. A wipe (`session_revoked`) removes
 * the database file, its store secret and key copies, PIN counter and
 * biometric entry, the tokens and the account entry. Wrong PINs never wipe:
 * they lock the store for a while, and a password sign-in allows a PIN reset
 * for that account (digitva-kfi). Sign-out and
 * re-enrolment wipe nothing: they drop the tokens and keep the store, its PIN
 * and biometric entries (owner decision 2026-10-27).
 */
import * as SecureStore from "expo-secure-store";
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { Platform } from "react-native";

import { APP_VERSION } from "./appVersion";
import { stableAccessJson } from "./accessKey";
import { allowPinReset, allowProfileDelete, clearProfileDeleteGrant, hasProfileDeleteGrant } from "./pinResetGrant";
import {
  accessCapabilities,
  ApiError,
  AUTH_API,
  parseAccessSummary,
  requestJson,
  requestRaw,
  type AccountDevice,
  type AccessSummary,
  type DeviceDecommissionResponse,
  type RawApiResponse,
} from "./api";
import { accountServerChanged, lacksServer, UNKNOWN_SERVER } from "./accountServer";
import { accountStoreIdentityIsInSelectedMode, accountStoreIdentityMode, assertAccountIdentityCanBeStored, assertAccountStoreIdentitySafe, loadAccountsForSlot } from "./accountStoreIdentity";
import { acceptedServerOrigin, DEMO_SERVER, EnrolmentError } from "./enrolment";
import { AccountStoreCollisionError, AlreadyEnrolledError, NotInSlotError, SessionRevokedError, SignInRequiredError } from "./authErrors";
import type { UnlockResult } from "./interviewerDb";
import { getOrCreatePlusDeviceIdentity } from "./offlineIdentity";
import { clearNotificationState, resetNotificationState } from "./notificationState";
import { attachmentMediaExtension } from "./workspace/media/path";
import { offlineCodingProjectIds } from "./codingCapabilities";
import { flushPerformanceTelemetry } from "./performanceTelemetry";

export { AccountStoreCollisionError, AlreadyEnrolledError, NotInSlotError, SessionRevokedError, SignInRequiredError } from "./authErrors";

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
  /** Last validated server answer; absent until sign-in or access refresh succeeds. */
  collection_access?: boolean;
  /** Registration reach is independent from permission to interview. */
  registration_access?: boolean;
  /** The own-registration list is available only to death reporters. */
  registered_deaths_access?: boolean;
  /** Explicit active workflow grants, refreshed from /me/access. */
  coding_access?: boolean;
  /** Project ids where self-coding and an active coder grant permit local coding. */
  offline_coding_access?: string[];
  /** Digest of the last validated coding scope; display cache only, never authorization. */
  coding_history_access?: string;
  reviewing_access?: boolean;
  /** The server refused the refresh token without revoking: sign in again, data kept. */
  needs_sign_in?: boolean;
  /** Signed out on this phone (with needs_sign_in): the encrypted store and PIN stay; signing in again shows the data. */
  signed_out?: boolean;
  /** session_revoked while unsent work remained: no new work, store kept, sign in again to send. */
  access_removed?: boolean;
  terms_required?: boolean;
  /** A global bearer gate keeps local work but blocks collection until fixed. */
  access_blocked?: "maintenance";
  /** Path C: a local account with no server session; sync, token refresh and polling skip it. */
  standalone?: boolean;
  /**
   * The server this account's session was opened on. Its tokens go to no other: a request is refused when the
   * slot's device is on a different server. Absent on standalone accounts and on accounts kept before slots.
   */
  server?: string;
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
/**
 * Active and Demo enrolments side by side (docs/policy/public-demo.md section
 * 10.1). Active keeps the keys above, so a phone enrolled before slots needs
 * no migration; Demo prefixes them `demo.`. `active_slot` missing means
 * Active. Tokens and interviewer stores stay keyed by user id.
 */
const ACTIVE_SLOT_KEY = "active_slot";
export type Slot = "active" | "demo";
let activeSlotGeneration = 0;
const tokensKey = (userId: string) => `tokens.${userId}`;
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

const termsListeners = new Set<() => void>();
const accountListeners = new Set<() => void>();
const accessListeners = new Set<(userId: string, access: AccessSummary) => Promise<void> | void>();
const accessRefreshes = new Map<string, Promise<AccessSummary | undefined>>();
let accountStorageQueue: Promise<void> = Promise.resolve();

function serializeAccountStorage<T>(write: () => Promise<T>): Promise<T> {
  const queued = accountStorageQueue.then(write);
  accountStorageQueue = queued.then(() => undefined, () => undefined);
  return queued;
}
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

/** The chosen slot; anything but "demo" (missing included) is Active. */
export async function loadActiveSlot(): Promise<Slot> {
  return (await SecureStore.getItemAsync(ACTIVE_SLOT_KEY, OPTIONS)) === "demo" ? "demo" : "active";
}

/** Choose the slot every reader below uses. Active deletes the key, leaving the store as before slots. */
export const setActiveSlot = (slot: Slot) => {
  activeSlotGeneration += 1;
  return slot === "demo"
    ? SecureStore.setItemAsync(ACTIVE_SLOT_KEY, slot, OPTIONS)
    : SecureStore.deleteItemAsync(ACTIVE_SLOT_KEY, OPTIONS);
};

async function assertSlotGeneration(slot: Slot, generation: number): Promise<void> {
  if (generation !== activeSlotGeneration) throw new NotInSlotError();
  const selected = await loadActiveSlot();
  if (generation !== activeSlotGeneration || selected !== slot) throw new NotInSlotError();
}

async function selectedSlotSnapshot(): Promise<{ slot: Slot; generation: number }> {
  const generation = activeSlotGeneration;
  const slot = await loadActiveSlot();
  await assertSlotGeneration(slot, generation);
  return { slot, generation };
}

/** `base` as the given slot stores it: Active keeps today's name, Demo prefixes `demo.`. */
export const slotKey = (slot: Slot, base: string) => (slot === "demo" ? `demo.${base}` : base);

// ponytail: every read resolves the slot again (one more SecureStore read); a
// module cache would need invalidation on every switch and enrolment.
export const loadDevice = async (slot?: Slot) =>
  readJson<Device>(slotKey(slot ?? (await loadActiveSlot()), DEVICE_KEY));
const loadDeviceSecret = async (slot?: Slot) =>
  SecureStore.getItemAsync(slotKey(slot ?? (await loadActiveSlot()), DEVICE_SECRET_KEY), OPTIONS);
export const loadAccounts = async (slot?: Slot) =>
  await loadAccountsForSlot(slot ?? (await loadActiveSlot())) as Account[];

async function loadTokens(userId: string): Promise<Tokens | undefined> {
  if (!(await accountStoreIdentityIsInSelectedMode(userId))) return undefined;
  return readJson<Tokens>(tokensKey(userId));
}

/**
 * Standalone is available only after every server account in both slots was explicitly signed out.
 * Expiry, locking and access refusals do not count as logout; unreadable account storage refuses access.
 */
export async function standaloneModeAvailable(): Promise<boolean> {
  try {
    const stored = await Promise.all((["active", "demo"] as const)
      .map((slot) => SecureStore.getItemAsync(slotKey(slot, ACCOUNTS_KEY), OPTIONS)));
    return stored.every((raw) => {
      const accounts: unknown = raw === null ? [] : JSON.parse(raw);
      return Array.isArray(accounts) && accounts.every((account: unknown) =>
        typeof account === "object" && account !== null &&
        "user_id" in account && typeof account.user_id === "string" &&
        "name" in account && typeof account.name === "string" &&
        (("standalone" in account && account.standalone === true) ||
          ("signed_out" in account && account.signed_out === true)),
      );
    });
  } catch {
    return false;
  }
}

/**
 * Read, change and write one slot's accounts, never the other's. `change`
 * returns undefined to write nothing; resolves whether it wrote.
 */
async function updateAccounts(slot: Slot, change: (accounts: Account[]) => Account[] | undefined): Promise<boolean> {
  const next = change(await loadAccounts(slot));
  if (!next) return false;
  await writeJson(slotKey(slot, ACCOUNTS_KEY), next);
  return true;
}

/**
 * updateAccounts on the slot that holds `userId`, whichever is chosen: a
 * write for a user never lands in the other slot's list. Writes nothing when
 * neither slot holds them.
 */
async function updateAccountsOf(userId: string, change: (accounts: Account[]) => Account[] | undefined): Promise<boolean> {
  for (const slot of ["active", "demo"] as const) {
    if ((await loadAccounts(slot)).some((account) => account.user_id === userId)) return updateAccounts(slot, change);
  }
  return false;
}

/**
 * Bind every account of `slot` (default: the chosen one) kept before accounts
 * recorded their server to that slot's device server, so a later enrolment on
 * another server hides them and refuses their tokens (accountServerChanged).
 * Writes once, and only when one lacks it; nothing without a device. Runs
 * before the device is forgotten, on sign-out, and on AppState reload.
 */
export async function bindLegacyAccounts(slot?: Slot): Promise<boolean> {
  const target = slot ?? (await loadActiveSlot());
  const device = await loadDevice(target);
  if (!device) return false;
  return updateAccounts(target, (accounts) =>
    accounts.some(lacksServer)
      ? accounts.map((account) => (lacksServer(account) ? { ...account, server: device.server } : account))
      : undefined,
  );
}

/**
 * The chosen slot's device and `userId`'s account in it, read from one slot,
 * for a request on that user's behalf. Throws `not_enrolled` without a device,
 * and NotInSlotError when the user is not in that slot (a switch or wipe
 * landed while the request was queued) or their account is bound to another
 * server: a token only ever goes to the server it was issued by.
 */
async function deviceFor(userId: string): Promise<{ slot: Slot; device: Device; account: Account }> {
  const slot = await loadActiveSlot();
  const [device, accounts] = await Promise.all([loadDevice(slot), loadAccounts(slot)]);
  if (!device) throw new Error("not_enrolled");
  const account = accounts.find((item) => item.user_id === userId);
  if (!account || accountServerChanged(account, device)) throw new NotInSlotError();
  return { slot, device, account };
}

/** List this signed-in account's live phone sessions; the server never returns credentials. */
export async function listMyDevices(userId: string): Promise<AccountDevice[]> {
  const { body } = await authedRequest<{ devices: AccountDevice[] }>(userId, "/api/v1/me/devices");
  if (!body || !Array.isArray(body.devices)) throw new ApiError(200, "malformed_response");
  return body.devices;
}

/** End one phone's sessions. A current-phone removal keeps its encrypted data and only requires sign-in again. */
export async function decommissionMyDevice(userId: string, deviceId: string): Promise<DeviceDecommissionResponse> {
  const { body } = await authedRequest<DeviceDecommissionResponse>(
    userId,
    `/api/v1/me/devices/${encodeURIComponent(deviceId)}`,
    { method: "DELETE" },
  );
  if (!body || body.decommissioned !== true || !Number.isInteger(body.sessions_ended) || typeof body.current !== "boolean") {
    throw new ApiError(200, "malformed_response");
  }
  if (body.current) {
    await markSignInRequired(userId);
    for (const listener of accountListeners) listener();
  }
  return body;
}

/** Refresh the grant summary through the authenticated token-rotation path. */
export function refreshAccessSummary(userId: string): Promise<AccessSummary | undefined> {
  const existing = accessRefreshes.get(userId);
  if (existing) return existing;
  const pending = refreshAccessSummaryOnce(userId).finally(() => {
    if (accessRefreshes.get(userId) === pending) accessRefreshes.delete(userId);
  });
  accessRefreshes.set(userId, pending);
  return pending;
}

function schedulePerformanceTelemetryFlush(userId: string): void {
  void flushPerformanceTelemetry(userId, (path, init) => authedRequest(userId, path, init)).catch(() => undefined);
}

async function refreshAccessSummaryOnce(userId: string): Promise<AccessSummary | undefined> {
  const mode = await accountStoreIdentityMode(userId);
  if (mode === "other") throw new NotInSlotError();
  if (mode === "missing") return undefined;
  const device = await loadDevice();
  const tokens = await loadTokens(userId);
  if (!device || !tokens) return undefined;
  try {
    const { body } = await authedRequest<unknown>(userId, "/api/v1/me/access");
    const access = await publishAccessSummary(userId, body);
    // Performance batches are optional and rate-limited; never delay access refresh or surface a telemetry error.
    schedulePerformanceTelemetryFlush(userId);
    return access;
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

/** Refresh access when an action depends on fresh authorization; offline is not a grant. */
export async function refreshAccessSummaryForAction(userId: string): Promise<AccessSummary> {
  const mode = await accountStoreIdentityMode(userId);
  if (mode === "other") throw new NotInSlotError();
  if (mode === "missing") throw new ApiError(401, "unauthorized");
  const device = await loadDevice();
  const tokens = await loadTokens(userId);
  if (!device || !tokens) throw new ApiError(401, "unauthorized");
  const { body } = await authedRequest<unknown>(userId, "/api/v1/me/access");
  const access = await publishAccessSummary(userId, body);
  schedulePerformanceTelemetryFlush(userId);
  return access;
}

async function publishAccessSummary(userId: string, value: unknown): Promise<AccessSummary> {
  let access: AccessSummary;
  try {
    access = parseAccessSummary(value);
  } catch (error) {
    await setAccountAccess(userId, false, false, false, false, false, []);
    throw error;
  }
  await setAccessBlocked(userId, undefined);
  const capabilities = accessCapabilities(access);
  await setAccountAccess(
    userId,
    capabilities.intake,
    capabilities.registerDeath,
    capabilities.registeredDeaths,
    access.roles.some((role) => role === "coder" || role === "coding_tester"),
    access.roles.includes("reviewer"),
    offlineCodingProjectIds(access),
    await digestStringAsync(CryptoDigestAlgorithm.SHA256, stableAccessJson({ roles: access.roles, projects: access.projects })),
  );
  for (const listener of accessListeners) await listener(userId, access);
  return access;
}

async function setAccountAccess(
  userId: string,
  collection: boolean,
  registration: boolean,
  registeredDeaths: boolean,
  coding: boolean,
  reviewing: boolean,
  offlineCoding: string[],
  codingHistoryAccess?: string,
): Promise<void> {
  const changed = await updateAccountsOf(userId, (accounts) => {
    if (!accounts.some((account) => account.user_id === userId &&
        (account.collection_access !== collection || account.registration_access !== registration ||
          account.registered_deaths_access !== registeredDeaths || account.coding_access !== coding ||
          account.reviewing_access !== reviewing ||
          account.coding_history_access !== codingHistoryAccess ||
          JSON.stringify(account.offline_coding_access ?? []) !== JSON.stringify(offlineCoding)))) return undefined;
    return accounts.map((account) => account.user_id === userId
      ? { ...account, collection_access: collection, registration_access: registration,
        registered_deaths_access: registeredDeaths, coding_access: coding, reviewing_access: reviewing,
        offline_coding_access: offlineCoding, coding_history_access: codingHistoryAccess }
      : account);
  });
  if (!changed) return;
  for (const listener of accountListeners) listener();
}

function isGlobalAccessGate(code: string | undefined): code is "maintenance" {
  return code === "maintenance";
}

interface EnrolReply {
  device_id: string;
  device_secret: string;
  project: { project_id: string; name: string };
  /** Password and sign-in QR replies: every eligible home (newer servers only). */
  projects?: unknown;
}

/** Throws AlreadyEnrolledError when `slot` holds a device: only re-enrolment (src/reEnrolConfirm.ts) empties it. */
async function refuseEnrolled(slot: Slot): Promise<void> {
  if (await loadDevice(slot)) throw new AlreadyEnrolledError();
}

/**
 * Keep the device record the server returned in `slot`, then choose that slot
 * (the sign-in that follows reads it). The secret is stored apart and sent
 * only to /sessions. The other slot's keys are untouched. Never overwrites:
 * throws AlreadyEnrolledError when the slot already holds a device. The
 * caller has locked every store first (src/AppState.tsx lockNow), since this
 * changes the chosen slot.
 */
async function storeEnrolment(slot: Slot, server: string, body: EnrolReply): Promise<Device> {
  await refuseEnrolled(slot);
  // The slot has no device, so an account still without a server lost it before servers were
  // recorded (an older app dropped the device): it may belong to another server. It is retired,
  // not bound to this one: tokens dropped, data kept, hidden until that person signs in again.
  const retired: string[] = [];
  await updateAccounts(slot, (accounts) => {
    if (!accounts.some(lacksServer)) return undefined;
    return accounts.map((account) => {
      if (!lacksServer(account)) return account;
      retired.push(account.user_id);
      return { ...account, server: UNKNOWN_SERVER, needs_sign_in: true };
    });
  });
  for (const userId of retired) await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
  const device: Device = {
    device_id: body.device_id,
    server,
    project_id: body.project.project_id,
    project_name: body.project.name,
  };
  await SecureStore.setItemAsync(slotKey(slot, DEVICE_SECRET_KEY), body.device_secret, OPTIONS);
  await writeJson(slotKey(slot, DEVICE_KEY), device);
  await setActiveSlot(slot);
  return device;
}

/** Collect Plus only: the install UUID the server binds to the device row; {} on the plain build and the web. */
async function clientDeviceUuid(): Promise<{ client_device_uuid?: string }> {
  const identity = await getOrCreatePlusDeviceIdentity();
  return identity ? { client_device_uuid: identity.uuid } : {};
}

/** POST /enroll and keep the device record in the Active slot, which becomes the chosen one. */
export async function enrolDevice(
  server: string,
  code: string,
  deviceName: string,
  appVersion: string,
): Promise<Device> {
  // Checked before the request too, so a refused enrolment leaves no device row on the server.
  await refuseEnrolled("active");
  const { body } = await requestJson<EnrolReply>(server, `${AUTH_API}/enroll`, {
    method: "POST",
    body: {
      code,
      device_name: deviceName,
      platform: Platform.OS === "ios" ? "ios" : "android",
      app_version: appVersion,
      ...(await clientDeviceUuid()),
    },
  });
  return storeEnrolment("active", server, body);
}

/**
 * POST /demo-enroll (public demo, no QR code): the demo account's username and
 * password enrol this phone on the demo server, kept in the Demo slot (which
 * becomes the chosen one) as a QR enrolment keeps its server in Active. The caller
 * passes a server the build's demo rule accepts (src/enrolment.ts).
 */
export async function enrolDemoDevice(
  server: string,
  username: string,
  password: string,
  deviceName: string,
  appVersion: string,
): Promise<Device> {
  await refuseEnrolled("demo");
  const { body } = await requestJson<EnrolReply>(server, `${AUTH_API}/demo-enroll`, {
    method: "POST",
    body: {
      username,
      password,
      device_name: deviceName,
      platform: Platform.OS === "ios" ? "ios" : "android",
      app_version: appVersion,
      ...(await clientDeviceUuid()),
    },
  });
  return storeEnrolment("demo", server, body);
}

/**
 * Drop `slot`'s enrolment (default: the chosen one), used when the server says
 * the device is revoked and by re-enrolment. Interviewer stores are untouched;
 * accounts with no recorded server are bound to the departing device's first.
 * An emptied Demo slot hands the phone back to Active, so Home never offers QR
 * enrolment into Demo; the caller has locked every store first, as for any
 * slot change (src/AppState.tsx lockNow).
 */
export async function forgetDevice(slot?: Slot): Promise<void> {
  const chosen = await loadActiveSlot();
  const target = slot ?? chosen;
  // Last chance to learn which server the slot's legacy accounts belong to.
  await bindLegacyAccounts(target);
  await SecureStore.deleteItemAsync(slotKey(target, DEVICE_SECRET_KEY), OPTIONS);
  await SecureStore.deleteItemAsync(slotKey(target, DEVICE_KEY), OPTIONS);
  if (target === "demo" && chosen === "demo") await setActiveSlot("active");
}

/**
 * POST /sessions with an email or canonical +91 mobile identifier; throws
 * ApiError. Uses `slot` (default: the chosen one, read once) for the device and
 * the account, and throws NotInSlotError, keeping neither the account nor its
 * tokens, when that slot is not (or no longer) the chosen one.
 */
export async function signIn(
  identifier: string,
  password: string,
  slot?: Slot,
  options: { forPinReset?: boolean } = {},
): Promise<Account> {
  const snapshot = await selectedSlotSnapshot();
  if (slot !== undefined && slot !== snapshot.slot) throw new NotInSlotError();
  slot ??= snapshot.slot;
  const device = await loadDevice(slot);
  const secret = await loadDeviceSecret(slot);
  if (!device || !secret) throw new Error("not_enrolled");
  const { body } = await requestJson<SessionBody>(device.server, `${AUTH_API}/sessions`, {
    method: "POST",
    // The device API keeps `email` as its backwards-compatible field name;
    // it accepts an email or the canonical +91 mobile identifier.
    body: {
      device_id: device.device_id,
      device_secret: secret,
      email: identifier,
      password,
      app_version: APP_VERSION,
    },
  });
  const account = await storeSession(slot, device.server, body, snapshot.generation);
  // Only the "Forgot PIN?" sign-in lets this account reset its own PIN, nobody else's.
  if (options.forPinReset) allowPinReset(account.user_id);
  return account;
}

type SessionBody = Tokens & { user: { user_id: string; name: string; email?: string | null }; access: unknown };

/**
 * Enrol and sign in to Active with account credentials on an accepted server.
 * Refuses the public Demo server, an occupied Active slot or Demo mode before
 * sending credentials; a failed or malformed reply stores nothing. The caller locks every store first.
 */
export async function passwordEnrolAndSignIn(
  server: string,
  identifier: string,
  password: string,
  deviceName: string,
  appVersion: string,
): Promise<EnrolledAccount> {
  const origin = acceptedServerOrigin(server, __DEV__);
  if (!origin || origin === DEMO_SERVER) throw new EnrolmentError("errServerNotAllowed");
  const snapshot = await selectedSlotSnapshot();
  if (snapshot.slot !== "active") throw new NotInSlotError();
  await refuseEnrolled("active");
  if (!identifier.trim() || !password) throw new ApiError(400, "invalid_request");
  const { body } = await requestJson<EnrolReply & SessionBody>(origin, `${AUTH_API}/password-enroll`, {
    method: "POST",
    body: {
      identifier: identifier.trim(),
      password,
      device_name: deviceName,
      platform: Platform.OS === "ios" ? "ios" : "android",
      app_version: appVersion,
      ...(await clientDeviceUuid()),
    },
  });
  if (!body || typeof body.device_id !== "string" || !body.device_id ||
    typeof body.device_secret !== "string" || !body.device_secret ||
    typeof body.project?.project_id !== "string" || typeof body.project.name !== "string" ||
    typeof body.user?.user_id !== "string" || !body.user.user_id || typeof body.user.name !== "string" ||
    typeof body.access_token !== "string" || !body.access_token ||
    typeof body.refresh_token !== "string" || !body.refresh_token ||
    typeof body.access_expires_at !== "string" || !Number.isFinite(Date.parse(body.access_expires_at)) ||
    typeof body.refresh_expires_at !== "string" || !Number.isFinite(Date.parse(body.refresh_expires_at)) ||
    (body.terms_required !== undefined && typeof body.terms_required !== "boolean")) {
    throw new ApiError(200, "malformed_response");
  }
  const access = parseAccessSummary(body.access);
  if (access.user.user_id !== body.user.user_id) throw new ApiError(200, "malformed_response");
  const account = await storeEnrolledSession("active", origin, { ...body, access }, snapshot);
  return { account, projects: enrolProjects(body.projects) };
}

/**
 * POST /sign-in-qr/redeem: one scan enrols this phone and opens the QR's user's
 * session, stored as enrolment plus password sign-in store them. The server
 * answers every failure with 404 `sign_in_qr_invalid`. The token is sent once
 * and is never logged or kept.
 */
export async function redeemSignInQr(
  server: string,
  token: string,
  deviceName: string,
  appVersion: string,
): Promise<EnrolledAccount> {
  const snapshot = await selectedSlotSnapshot();
  // Before the request, so a refusal does not spend the one-time token.
  await refuseEnrolled("active");
  const { body } = await requestJson<EnrolReply & SessionBody>(server, `${AUTH_API}/sign-in-qr/redeem`, {
    method: "POST",
    body: {
      token,
      device_name: deviceName,
      platform: Platform.OS === "ios" ? "ios" : "android",
      app_version: appVersion,
      ...(await clientDeviceUuid()),
    },
  });
  const account = await storeEnrolledSession("active", server, body, snapshot);
  return { account, projects: enrolProjects(body.projects) };
}

/** A home project the enrolment reply offers (docs/policy/mobile-sign-in.md, home project). */
export type EnrolProject = { project_id: string; name: string };
/** The enrolled account and every project it may make this phone's home; an older server lists none. */
export type EnrolledAccount = { account: Account; projects: EnrolProject[] };

/** Keep only well-formed `projects` entries; anything else (or an older server's absent list) is no choice. */
function enrolProjects(value: unknown): EnrolProject[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is EnrolProject =>
    typeof item?.project_id === "string" && !!item.project_id && typeof item.name === "string");
}

/** The project picked at enrolment, kept until the worklist opens the account's store and saves it. */
const pickedHomeProjects = new Map<string, string>();

/** Hand the enrolment pick to the worklist once; undefined when none is waiting. */
export function takePickedHomeProject(userId: string): string | undefined {
  const projectId = pickedHomeProjects.get(userId);
  pickedHomeProjects.delete(userId);
  return projectId;
}

/** POST /auth/devices/current/project: make the picked project this phone's home on the server, then hand it to the worklist. */
export async function setDeviceHomeProject(userId: string, projectId: string): Promise<void> {
  const reply = await authedRequest(
    userId, `${AUTH_API}/devices/current/project`, { method: "POST", body: { project_id: projectId } });
  // The stored device record names the home project on Home, sign-in and settings.
  const slot = await loadActiveSlot();
  const device = await loadDevice(slot);
  if (device) {
    await writeJson(slotKey(slot, DEVICE_KEY), {
      ...device, project_id: projectId, project_name: (reply.body as { project?: { name?: string } } | undefined)?.project?.name ?? device.project_name,
    });
  }
  pickedHomeProjects.set(userId, projectId);
}

/**
 * Keep the account and tokens a session reply opened (password sign-in and
 * sign-in QR redeem alike) in `slot`, the account bound to `server`. Throws
 * NotInSlotError and keeps nothing when `slot` is no longer the chosen one.
 */
async function storeSession(slot: Slot, server: string, body: SessionBody, generation: number): Promise<Account> {
  return serializeAccountStorage(() => storeSessionSerialized(slot, server, body, generation));
}

async function storeEnrolledSession(
  slot: Slot,
  server: string,
  body: EnrolReply & SessionBody,
  snapshot: { slot: Slot; generation: number },
): Promise<Account> {
  return serializeAccountStorage(async () => {
    await assertSlotGeneration(snapshot.slot, snapshot.generation);
    const userId = String(body.user.user_id);
    const accounts = await loadAccounts(slot);
    await assertAccountIdentityCanBeStored(userId, slot, server, false);
    if (!accounts.some((item) => item.user_id === userId) &&
      await SecureStore.getItemAsync(tokensKey(userId), OPTIONS) !== null) {
      throw new AccountStoreCollisionError();
    }
    await assertSlotGeneration(snapshot.slot, snapshot.generation);
    const generationAfterEnrolment = activeSlotGeneration + 1;
    await storeEnrolment(slot, server, body);
    if (generationAfterEnrolment !== activeSlotGeneration) throw new NotInSlotError();
    return storeSessionSerialized(slot, server, body, generationAfterEnrolment);
  });
}

async function storeSessionSerialized(slot: Slot, server: string, body: SessionBody, generation: number): Promise<Account> {
  await assertSlotGeneration(slot, generation);
  const device = await loadDevice(slot);
  const account: Account = {
    user_id: String(body.user.user_id),
    name: body.user.name,
    server,
    ...(body.terms_required ? { terms_required: true } : {}),
  };
  await assertAccountIdentityCanBeStored(account.user_id, slot, server, false, device?.server);
  let existingAccounts: Account[] = [];
  const beforeWrite = await loadAccounts(slot);
  if (!beforeWrite.some((item) => item.user_id === account.user_id) &&
    await SecureStore.getItemAsync(tokensKey(account.user_id), OPTIONS) !== null) {
    throw new AccountStoreCollisionError();
  }
  await assertSlotGeneration(slot, generation);
  await updateAccounts(slot, (accounts) => {
    existingAccounts = accounts;
    const pending = { ...account, needs_sign_in: true, signed_out: true };
    return [...accounts.filter((a) => a.user_id !== account.user_id), pending];
  });
  await assertSlotGeneration(slot, generation);
  await assertAccountIdentityCanBeStored(account.user_id, slot, server, false, device?.server);
  await assertSlotGeneration(slot, generation);
  await writeTokensUnchecked(account.user_id, body);
  await updateAccounts(slot, (accounts) =>
    accounts.some((item) => item.user_id === account.user_id)
      ? accounts.map((item) => item.user_id === account.user_id ? account : item)
      : undefined,
  );
  await Promise.all(
    [...new Set([...existingAccounts.map(({ user_id }) => user_id), account.user_id])]
      .map((userId) => resetNotificationState(userId)),
  );
  await publishAccessSummary(account.user_id, body.access);
  return account;
}

async function writeTokensUnchecked(userId: string, t: Tokens): Promise<void> {
  const tokens: Tokens = {
    access_token: t.access_token,
    access_expires_at: t.access_expires_at,
    refresh_token: t.refresh_token,
    refresh_expires_at: t.refresh_expires_at,
  };
  await writeJson(tokensKey(userId), tokens);
}

async function saveTokens(
  userId: string,
  t: Tokens,
  slot: Slot,
  server: string,
  expectedRefreshToken: string,
): Promise<void> {
  await serializeAccountStorage(async () => {
    if (!(await loadAccounts(slot)).some((account) => account.user_id === userId)) throw new NotInSlotError();
    await assertAccountIdentityCanBeStored(userId, slot, server, false, server);
    const current = await readJson<Tokens>(tokensKey(userId));
    if (current?.refresh_token !== expectedRefreshToken) throw new SignInRequiredError();
    await writeTokensUnchecked(userId, t);
  });
}

/**
 * Path C: keep a local standalone account (no server, no tokens) in the Active slot, and choose Active.
 * Idempotent: an existing entry is returned unchanged. Collection access is granted locally because nothing
 * can refresh it. Requires Active and explicit logout of every server account in both slots.
 * Throws standalone_server_session_active before writing when a server account has not signed out.
 */
export async function createStandaloneAccount(userId: string, name: string): Promise<Account> {
  return serializeAccountStorage(async () => {
    const snapshot = await selectedSlotSnapshot();
    // Standalone accounts belong to Active; switching here would skip the lock, so Demo refuses.
    if (snapshot.slot === "demo") throw new NotInSlotError();
    if (!(await standaloneModeAvailable())) throw new Error("standalone_server_session_active");
    await assertAccountIdentityCanBeStored(userId, "active", undefined, true);
    await assertSlotGeneration("active", snapshot.generation);
    const account: Account = {
      user_id: userId, name, standalone: true,
      collection_access: true, registration_access: false, registered_deaths_access: false,
      coding_access: false, reviewing_access: false,
    };
    let existing: Account | undefined;
    await assertSlotGeneration("active", snapshot.generation);
    await updateAccounts("active", (accounts) => {
      existing = accounts.find((a) => a.user_id === userId);
      return existing ? undefined : [...accounts, account];
    });
    if (existing) return existing;
    for (const listener of accountListeners) listener();
    return account;
  });
}

/** Wipe one interviewer: database, tokens, account entry. Nobody else's. */
export async function wipeInterviewer(userId: string): Promise<void> {
  await serializeAccountStorage(async () => {
    await assertAccountStoreIdentitySafe(userId);
    const clearNotifications = clearNotificationState(userId);
    const { deleteInterviewerDb } = require("./interviewerDb") as typeof import("./interviewerDb");
    await deleteInterviewerDb(userId);
    await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
    await updateAccountsOf(userId, (accounts) => accounts.filter((a) => a.user_id !== userId));
    await clearNotifications;
  });
}

/** The server refused this interviewer's refresh without revoking: drop the dead tokens, flag the account, keep its data. */
async function markSignInRequired(userId: string, accessRemoved = false): Promise<void> {
  await serializeAccountStorage(async () => {
    await assertAccountStoreIdentitySafe(userId);
    await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
    await updateAccountsOf(userId, (accounts) =>
      accounts.map((a) =>
        a.user_id === userId
          ? { ...a, needs_sign_in: true, ...(accessRemoved ? { access_removed: true } : {}) }
          : a,
      ),
    );
  });
}

/**
 * session_revoked: wipe only when the unlocked store is known to hold no
 * unsent work; otherwise keep the encrypted store and lock the account into
 * the read-only "access removed" state.
 */
async function revokeInterviewer(userId: string): Promise<SessionRevokedError> {
  const { unsentWorkCount } = require("./interviewerDb") as typeof import("./interviewerDb");
  // ponytail: a locked store counts as "maybe unsent" and is kept; the next
  // unlock finishes the wipe if it turns out empty (unlockInterviewer).
  if ((await unsentWorkCount(userId)) === 0) {
    await wipeInterviewer(userId);
    return new SessionRevokedError();
  }
  await markSignInRequired(userId, true);
  return new SessionRevokedError(true);
}

/** Best effort: tell the server this phone's session for *userId* is over. */
async function endServerSession(userId: string): Promise<void> {
  try {
    await authedRequest(userId, `${AUTH_API}/sessions/current`, {
      method: "DELETE",
    });
  } catch {
    // Offline or already revoked: the local step still happens.
  }
}

/**
 * Sign out: end the server session and drop this interviewer's tokens. Nothing
 * is deleted (owner decision 2026-10-27): the encrypted store, its PIN and the
 * profile stay, listed as signed out, and signing in again with the same
 * account shows the data, unsent work included. A standalone account has no
 * session, so there is nothing to end. The caller locks the stores first
 * (AppState lockNow), so open work is saved and nothing stays open.
 */
export async function signOut(userId: string): Promise<void> {
  const standalone = (await loadAccounts()).find((a) => a.user_id === userId)?.standalone;
  if (standalone) return;
  // Re-enrolment signs out before it forgets the device: bind legacy accounts while the server is known.
  await bindLegacyAccounts();
  await endServerSession(userId);
  await serializeAccountStorage(async () => {
    await assertAccountStoreIdentitySafe(userId);
    await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
    await updateAccountsOf(userId, (accounts) =>
      accounts.map((a) => (a.user_id === userId ? { ...a, needs_sign_in: true, signed_out: true } : a)),
    );
    for (const listener of accountListeners) listener();
  });
}

/**
 * Delete my account, public demo (docs/policy/public-demo.md section 9a): the server checks `password` and
 * deletes the account at once, then this phone wipes that profile (store, unsent work included, tokens, entry).
 * The server also deleted the devices only this account used, so a Demo slot left with no accounts forgets its
 * device (back to Active). The caller locks the stores first (AppState lockNow), as for any slot change.
 * Throws ApiError (`wrong_password`, `deletion_refused` with `payload.reason`) and deletes nothing locally then.
 */
export async function deleteDemoAccount(userId: string, password: string): Promise<void> {
  await authedRequest(userId, "/api/v1/me/account/delete", { method: "POST", body: { password } });
  await wipeInterviewer(userId);
  if ((await loadAccounts("demo")).length === 0 && (await loadDevice("demo"))) await forgetDevice("demo");
  for (const listener of accountListeners) listener();
}

/**
 * Delete my account, staff: ask the programme team (docs/policy/public-privacy-and-data-requests.md section 8).
 * The session identifies the account; a repeat while one is pending is a no-op on the server. Nothing changes here.
 */
export async function requestAccountDeletion(userId: string): Promise<void> {
  await authedRequest(userId, "/api/v1/me/deletion-request", { method: "POST", body: {} });
}

/**
 * Try the interviewer's PIN (src/interviewerDb.ts: wrong PINs lock, never
 * wipe). A right PIN on an account whose access was removed while its store
 * was locked finishes that revoke's wipe when nothing is unsent.
 */
export async function unlockInterviewer(
  userId: string,
  pin: string,
): Promise<UnlockResult> {
  const { unlockInterviewerDb, unsentWorkCount } = require("./interviewerDb") as typeof import("./interviewerDb");
  const result = await unlockInterviewerDb(userId, pin);
  if (!result.ok) return result;
  // A revoke that found the store locked kept it; now it can be counted.
  const account = (await loadAccounts()).find((item) => item.user_id === userId);
  if (account?.access_removed && (await unsentWorkCount(userId)) === 0) {
    await wipeInterviewer(userId);
    return { ok: false, failures: 0, wipe: true, revoked: true };
  }
  return result;
}

// One refresh in flight per interviewer. Two concurrent 401s must not both
// spend the same refresh token: reuse of a rotated token revokes the session.
const refreshing = new Map<string, Promise<Tokens>>();
const refreshingAccessTokens = new Map<string, string>();

/** Authenticated native Image/Audio source with a short-lived, memory-only bearer header. */
export async function getAuthenticatedAttachmentSource(
  userId: string,
  path: string,
): Promise<{ uri: string; headers: { Authorization: string } }> {
  if (!attachmentMediaExtension(path)) throw new Error("invalid_attachment_path");
  // Device and account from one slot (deviceFor); any refusal there means no source.
  const usable = (account: Account) => !account.needs_sign_in && !account.terms_required && !account.access_blocked;
  const [first, tokens] = await Promise.all([
    deviceFor(userId).catch(() => undefined),
    loadTokens(userId),
  ]);
  if (!first || !tokens?.access_token || !usable(first.account)) throw new SignInRequiredError();
  const { device } = first;

  let current = tokens;
  const pendingRefresh = refreshing.get(userId);
  if (pendingRefresh) current = await pendingRefresh;
  const expiresAt = Date.parse(current.access_expires_at);
  if (!Number.isFinite(expiresAt) || expiresAt <= Date.now() + 60_000) {
    try {
      current = await refresh(userId, device.server);
    } catch (error) {
      if (error instanceof NotInSlotError) throw new SignInRequiredError();
      throw error;
    }
  }
  const refreshedExpiry = Date.parse(current.access_expires_at);
  if (!Number.isFinite(refreshedExpiry) || refreshedExpiry <= Date.now()) throw new SignInRequiredError();

  const [latest, latestTokens] = await Promise.all([
    deviceFor(userId).catch(() => undefined),
    loadTokens(userId),
  ]);
  if (!latest || latest.device.device_id !== device.device_id || latest.device.server !== device.server
    || !latestTokens?.access_token || !usable(latest.account)) {
    throw new SignInRequiredError();
  }
  const latestExpiry = Date.parse(latestTokens.access_expires_at);
  if (!Number.isFinite(latestExpiry) || latestExpiry <= Date.now()) throw new SignInRequiredError();
  const uri = new URL(path, `${device.server.replace(/\/+$/, "")}/`).toString();
  return { uri, headers: { Authorization: `Bearer ${latestTokens.access_token}` } };
}

function refresh(userId: string, server: string): Promise<Tokens> {
  let pending = refreshing.get(userId);
  if (!pending) {
    pending = doRefresh(userId, server).finally(() => {
      refreshing.delete(userId);
      refreshingAccessTokens.delete(userId);
    });
    refreshing.set(userId, pending);
  }
  return pending;
}

async function doRefresh(userId: string, server: string): Promise<Tokens> {
  const snapshot = await selectedSlotSnapshot();
  const current = await loadTokens(userId);
  if (!current) throw new SignInRequiredError();
  // Device, account and secret from one slot. A switch since the caller read the server, or an account bound
  // to another server: never send this slot's device secret or the refresh token to the wrong server.
  const { slot, device } = await deviceFor(userId);
  if (slot !== snapshot.slot) throw new NotInSlotError();
  if (device.server !== server) throw new NotInSlotError();
  const secret = await loadDeviceSecret(slot);
  await assertSlotGeneration(snapshot.slot, snapshot.generation);
  try {
    const { body } = await requestJson<Tokens & { access: unknown }>(
      server,
      `${AUTH_API}/sessions/refresh`,
      {
        method: "POST",
        body: {
          refresh_token: current.refresh_token,
          device_id: device.device_id,
          device_secret: secret,
          app_version: APP_VERSION,
        },
      },
    );
    // Once sent, a refresh response remains bound to the slot and origin that issued it. The queued save
    // revalidates that binding and the rotated-token predecessor, even if the user switches slots meanwhile.
    await saveTokens(userId, body, slot, device.server, current.refresh_token);
    refreshingAccessTokens.set(userId, body.access_token);
    await setTermsRequired(userId, body.terms_required === true);
    await publishAccessSummary(userId, body.access);
    return body;
  } catch (error) {
    throw await classifyAuthError(userId, error);
  }
}

/**
 * Map a refused call to what the app does. Only `session_revoked` wipes
 * (and only a store with nothing unsent, revokeInterviewer);
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
    if (!accessRefreshes.has(userId)) await refreshAccessSummary(userId);
  }
  if (error.status === 401 && error.code === "session_revoked") return revokeInterviewer(userId);
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
 * Throws SessionRevokedError (store wiped, or kept read-only when work is unsent), SignInRequiredError,
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
    /** A file as the raw request body (src/attachmentUpload.ts). */
    rawBody?: { bytes: Uint8Array<ArrayBuffer>; sha256?: string };
    /** The route answers a JSON list (src/api.ts `ClientRequestOptions.allowList`). */
    allowList?: boolean;
  } = {},
): Promise<{ status: number; body: T }> {
  const { device } = await deviceFor(userId);
  const tokens = await loadTokens(userId);
  if (!tokens) throw new SignInRequiredError();
  const { bodyFactory, ...requestInit } = init;
  const initialBody = bodyFactory ? bodyFactory() : requestInit.body;
  let unauthorized: ApiError | undefined;
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
    unauthorized = error;
  }
  const latest = await loadTokens(userId);
  if (tokens.access_token === refreshingAccessTokens.get(userId)) {
    throw await classifyAuthError(userId, unauthorized);
  }
  const next = latest && latest.access_token !== tokens.access_token
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

/** Authenticated raw response with the same refresh lock and one-401 retry as JSON calls. */
export async function authedRawRequest(
  userId: string,
  path: string,
  init: { ifNoneMatch?: string; acceptGzip?: boolean; timeoutMs?: number } = {},
): Promise<RawApiResponse> {
  const { device } = await deviceFor(userId);
  const tokens = await loadTokens(userId);
  if (!tokens) throw new SignInRequiredError();
  try {
    return await requestRaw(device.server, path, { ...init, token: tokens.access_token });
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 401) throw await classifyAuthError(userId, error);
    if (error.code === "session_revoked") throw await classifyAuthError(userId, error);
  }
  const latest = await loadTokens(userId);
  const next = latest && latest.access_token !== tokens.access_token
    ? latest
    : await refresh(userId, device.server);
  try {
    return await requestRaw(device.server, path, { ...init, token: next.access_token });
  } catch (error) {
    throw await classifyAuthError(userId, error);
  }
}

async function setTermsRequired(
  userId: string,
  required: boolean,
): Promise<void> {
  const changed = await updateAccountsOf(userId, (accounts) => {
    if (
      !accounts.some(
        (account) =>
          account.user_id === userId &&
          (account.terms_required === true) !== required,
      )
    )
      return undefined;
    return accounts.map((account) => {
      if (account.user_id !== userId) return account;
      const { terms_required: _previous, ...rest } = account;
      return required ? { ...rest, terms_required: true } : rest;
    });
  });
  if (!changed) return;
  for (const listener of termsListeners) listener();
  for (const listener of accountListeners) listener();
}

async function setAccessBlocked(
  userId: string,
  blocked: "maintenance" | undefined,
): Promise<void> {
  const changed = await updateAccountsOf(userId, (accounts) => {
    let found = false;
    const next = accounts.map((account) => {
      if (account.user_id !== userId || account.access_blocked === blocked) return account;
      found = true;
      if (!blocked) {
        const { access_blocked: _blocked, ...rest } = account;
        return rest;
      }
      return { ...account, access_blocked: blocked };
    });
    return found ? next : undefined;
  });
  if (!changed) return;
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

/** The slot whose account list holds `userId`, or undefined when neither does. */
async function slotHolding(userId: string): Promise<Slot | undefined> {
  for (const slot of ["active", "demo"] as const) {
    if ((await loadAccounts(slot)).some((account) => account.user_id === userId)) return slot;
  }
  return undefined;
}

/** Thrown when a password sign-in names a different account than the profile it was meant for. */
export class WrongAccountError extends Error {
  constructor() {
    super("wrong_account");
    this.name = "WrongAccountError";
  }
}

/**
 * Check a password for `userId` on this device (docs/policy/mobile-sign-in.md section 10): POST /auth/sessions with
 * the slot's device credentials, then end that session at once (DELETE /auth/sessions/current). Stores nothing:
 * no tokens, no account change, no store opened. Throws ApiError for a refused sign-in and WrongAccountError when
 * the credentials belong to another account (whose fresh session is ended too).
 */
async function verifyPassword(userId: string, identifier: string, password: string): Promise<void> {
  const slot = await slotHolding(userId);
  const device = slot && (await loadDevice(slot));
  const secret = slot && (await loadDeviceSecret(slot));
  if (!device || !secret) throw new Error("not_enrolled");
  const { body } = await requestJson<SessionBody>(device.server, `${AUTH_API}/sessions`, {
    method: "POST",
    body: { device_id: device.device_id, device_secret: secret, email: identifier, password, app_version: APP_VERSION },
  });
  try {
    await requestJson(device.server, `${AUTH_API}/sessions/current`, { method: "DELETE", token: body.access_token });
  } catch {
    // Best effort, as endServerSession: the session is short-lived and holds no tokens on this phone.
  }
  if (String(body.user?.user_id) !== userId) throw new WrongAccountError();
}

/**
 * Recovery for a locked profile with no PIN reset copy: a password sign-in for the same account, then that
 * session is signed out. The encrypted store stays untouched; the profile is listed as signed out (so the phone
 * can add profiles or go standalone, standaloneModeAvailable) and its PIN still opens the data after a sign-in.
 */
export async function recoverSignOut(userId: string, identifier: string, password: string): Promise<void> {
  await verifyPassword(userId, identifier, password);
  await serializeAccountStorage(async () => {
    await assertAccountStoreIdentitySafe(userId);
    await SecureStore.deleteItemAsync(tokensKey(userId), OPTIONS);
    await updateAccountsOf(userId, (accounts) =>
      accounts.map((a) => (a.user_id === userId ? { ...a, needs_sign_in: true, signed_out: true } : a)),
    );
    for (const listener of accountListeners) listener();
  });
}

/** Password check before Delete profile: on success the unlock screen may delete `userId` within the window. */
export async function verifyPasswordForDelete(userId: string, identifier: string, password: string): Promise<void> {
  await verifyPassword(userId, identifier, password);
  allowProfileDelete(userId);
}

export { hasProfileDeleteGrant, PROFILE_DELETE_WINDOW_MS } from "./pinResetGrant";

/** Refused locally before anything is deleted or sent: unsent work, or an unknown count without the typed confirmation. */
export class ProfileDeleteRefusedError extends Error {
  constructor(public readonly code: "unsent_work" | "confirmation_required" | "not_verified") {
    super(code);
    this.name = "ProfileDeleteRefusedError";
  }
}

/** A deletion report not yet accepted, kept in device-level storage (outside every profile's store). */
interface QueuedProfileDeletion {
  slot: Slot;
  device_id: string;
  user_id: string;
  unsent_count: number | null;
  loss_confirmed: boolean;
}
const PROFILE_DELETIONS_KEY = "profile_deletions";
const loadQueuedDeletions = async () => (await readJson<QueuedProfileDeletion[]>(PROFILE_DELETIONS_KEY)) ?? [];

/**
 * Send one report with the device credentials. "done" on 200/201 and on a reply that can never succeed for this
 * report (404 older server, 401/403: device or profile unknown there), "retry" offline, on 429 and on 5xx; 400 and
 * 409 throw the ApiError (the server refused the deletion).
 */
async function sendDeletionReport(report: QueuedProfileDeletion): Promise<"done" | "retry"> {
  const device = await loadDevice(report.slot);
  const secret = await loadDeviceSecret(report.slot);
  // The device was forgotten or re-enrolled: its credentials are gone, nothing can carry this report.
  if (!device || !secret || device.device_id !== report.device_id) return "done";
  try {
    await requestJson(device.server, `${AUTH_API}/profile-deletions`, {
      method: "POST",
      body: {
        device_id: report.device_id,
        device_secret: secret,
        user_id: report.user_id,
        unsent_count: report.unsent_count,
        loss_confirmed: report.loss_confirmed,
      },
    });
    return "done";
  } catch (error) {
    if (!(error instanceof ApiError) || error.status === 429 || error.status >= 500) return "retry";
    if (error.status === 400 || error.status === 409) throw error;
    return "done";
  }
}

const sameReport = (a: QueuedProfileDeletion, b: QueuedProfileDeletion) => a.user_id === b.user_id && a.device_id === b.device_id;

/** Change the queue under the account-storage lock (never held across a network call); empty deletes the key. */
function updateQueuedDeletions(change: (queued: QueuedProfileDeletion[]) => QueuedProfileDeletion[]): Promise<void> {
  return serializeAccountStorage(async () => {
    const next = change(await loadQueuedDeletions());
    if (next.length) await writeJson(PROFILE_DELETIONS_KEY, next);
    else await SecureStore.deleteItemAsync(PROFILE_DELETIONS_KEY, OPTIONS);
  });
}

/**
 * Delete profile (docs/policy/mobile-sign-in.md section 10). Allowed only after a check: the store is open (a PIN
 * unlock; its count is re-read here and wins over `unsentCount`) or a password grant (hasProfileDeleteGrant).
 * Refuses a non-zero count and a null count without `lossConfirmed`. A server profile is reported first: a 400/409
 * refusal throws the ApiError and deletes nothing; offline or 5xx deletes anyway and queues the report for
 * sendQueuedProfileDeletions. Then wipeInterviewer removes this profile only. A standalone profile sends nothing.
 */
export async function deleteProfile(userId: string, unsentCount: number | null, lossConfirmed: boolean): Promise<void> {
  const { unsentWorkCount } = require("./interviewerDb") as typeof import("./interviewerDb");
  const storeCount = await unsentWorkCount(userId);
  if (storeCount === undefined && !hasProfileDeleteGrant(userId)) throw new ProfileDeleteRefusedError("not_verified");
  const count = storeCount ?? unsentCount;
  if (count !== null && count > 0) throw new ProfileDeleteRefusedError("unsent_work");
  if (count === null && !lossConfirmed) throw new ProfileDeleteRefusedError("confirmation_required");
  const slot = await slotHolding(userId);
  const account = slot && (await loadAccounts(slot)).find((a) => a.user_id === userId);
  const device = slot && (await loadDevice(slot));
  if (account && !account.standalone && slot && device) {
    const report: QueuedProfileDeletion = {
      slot,
      device_id: device.device_id,
      user_id: userId,
      unsent_count: count,
      loss_confirmed: count === null && lossConfirmed,
    };
    if ((await sendDeletionReport(report)) === "retry") {
      await updateQueuedDeletions((queued) => [...queued.filter((q) => !sameReport(q, report)), report]);
    }
  }
  clearProfileDeleteGrant(userId);
  await wipeInterviewer(userId);
  for (const listener of accountListeners) listener();
}

/**
 * Resend queued deletion reports (called on each sync). Reads a snapshot, sends without the lock, then removes
 * only the accepted or dropped entries (by user and device) from the queue as it is then, so a report queued
 * meanwhile is kept. A 400/409 on a resend drops the report: the profile is already gone from this phone.
 */
export async function sendQueuedProfileDeletions(): Promise<void> {
  const snapshot = await serializeAccountStorage(loadQueuedDeletions);
  if (!snapshot.length) return;
  const finished: QueuedProfileDeletion[] = [];
  for (const report of snapshot) {
    try {
      if ((await sendDeletionReport(report)) === "done") finished.push(report);
    } catch {
      finished.push(report); // refused for good
    }
  }
  if (finished.length) await updateQueuedDeletions((queued) => queued.filter((q) => !finished.some((f) => sameReport(f, q))));
}
