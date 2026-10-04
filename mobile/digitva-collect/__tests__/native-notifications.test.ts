const mockSecure = new Map<string, string>();
const mockAuthedRequest = jest.fn();
const mockSync = jest.fn();
const mockRefresh = jest.fn();
let mockSecureUnavailable = false;

jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => {
    if (mockSecureUnavailable) throw new Error("SecureStore unavailable");
    return mockSecure.get(key) ?? null;
  }),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (mockSecureUnavailable) throw new Error("SecureStore unavailable");
    mockSecure.set(key, value);
  }),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) =>
    `hash-${Array.from(value).map((char) => char.charCodeAt(0).toString(16)).join("")}`),
}));
jest.mock("../src/auth", () => ({
  authedRequest: (...args: unknown[]) => mockAuthedRequest(...args),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true }));
jest.mock("../src/sync", () => ({
  syncInterviewer: (...args: unknown[]) => mockSync(...args),
  refreshReferenceData: (...args: unknown[]) => mockRefresh(...args),
}));

import { pollAccountNotifications, refreshNativeNotifications, runNativeSync } from "../src/nativeNotificationSync";
import {
  clearNotificationState,
  finishNotificationSync,
  notificationStateGeneration,
  readNotificationState,
  recordNotificationPoll,
  resetNotificationState,
  runNotificationPoll,
} from "../src/notificationState";

const notification = (id: number) => ({
  id,
  kind: "future_kind",
  created_at: "2026-10-05T09:30:00+00:00",
  project_id: "ABC01",
  death_id: null,
  draft_id: null,
  va_sid: null,
});

const page = (notifications: unknown[], next_cursor?: number) => ({
  notifications,
  next_cursor: next_cursor ?? (notifications.length ? (notifications.at(-1) as { id: number }).id : 0),
});

beforeEach(() => {
  mockSecure.clear();
  mockAuthedRequest.mockReset();
  mockSync.mockReset();
  mockRefresh.mockReset();
  mockSecureUnavailable = false;
  mockSync.mockResolvedValue({ sent: 0, failed: 0, remaining: 0, supersededUniqueIds: [] });
  mockRefresh.mockResolvedValue({ projects: [] });
});

it("keeps cursor and pending sync isolated by account and persists only metadata", async () => {
  mockAuthedRequest.mockImplementation(async (userId: string) => ({
    body: page(userId === "account-a" ? [notification(4)] : []),
  }));
  await pollAccountNotifications("account-a");
  await pollAccountNotifications("account-b");

  expect(await readNotificationState("account-a")).toMatchObject({ cursor: 4, pendingSync: true });
  expect(await readNotificationState("account-b")).toMatchObject({ cursor: 0, pendingSync: false });
  for (const [key, value] of mockSecure) {
    if (!key.startsWith("notification_state.")) continue;
    expect(key).not.toContain("account-");
    expect(value).not.toMatch(/future_kind|ABC01|death_id|answer|name/i);
  }
});

it("preserves a validated cursor and requests sync after malformed or uncertain polling", async () => {
  await recordNotificationPoll("metadata-malformed", 8, false);
  mockAuthedRequest.mockResolvedValue({ body: { notifications: "bad", next_cursor: 9 } });

  await pollAccountNotifications("metadata-malformed");

  expect(await readNotificationState("metadata-malformed")).toMatchObject({
    cursor: 8,
    pendingSync: true,
  });
});

it("recovers malformed stored metadata to cursor zero with a pending full sync", async () => {
  const userId = "corrupt-metadata";
  const hash = Array.from(userId).map((char) => char.charCodeAt(0).toString(16)).join("");
  mockSecure.set(`notification_state.v1.hash-${hash}`, "not-json");

  expect(await readNotificationState(userId)).toMatchObject({
    cursor: 0,
    pendingSync: true,
    pendingRevision: 1,
  });
});

it("does not restore metadata when a poll finishes after an account wipe", async () => {
  let resolveRequest!: (value: unknown) => void;
  mockAuthedRequest.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve; }));
  const poll = pollAccountNotifications("wiped-account");
  await Promise.resolve();
  await Promise.resolve();
  await clearNotificationState("wiped-account");
  resolveRequest({ body: page([notification(3)]) });
  await poll;

  expect(notificationStateGeneration("wiped-account")).toBeGreaterThan(0);
  expect([...mockSecure.keys()].some((key) => key.startsWith("notification_state."))).toBe(false);
});

it("coalesces manual sync and keeps a new nudge pending while sync is running", async () => {
  await recordNotificationPoll("sync-account", 1, true);
  let finishSync!: (value: unknown) => void;
  mockSync.mockReturnValue(new Promise((resolve) => { finishSync = resolve; }));
  const db = {} as never;
  const first = runNativeSync("sync-account", db);
  const second = runNativeSync("sync-account", db);
  expect(second).toBe(first);
  await Promise.resolve();
  await Promise.resolve();
  await recordNotificationPoll("sync-account", 2, true);
  finishSync({ sent: 0, failed: 0, remaining: 0, supersededUniqueIds: [] });
  await first;

  expect(mockSync).toHaveBeenCalledTimes(1);
  expect(await readNotificationState("sync-account")).toMatchObject({
    cursor: 2,
    pendingSync: true,
  });
});

it("shares the minimum poll interval across foreground and background callers", async () => {
  let finish!: () => void;
  const foreground = runNotificationPoll("shared-poll", () => new Promise<void>((resolve) => { finish = resolve; }));
  const backgroundTask = jest.fn(async () => undefined);
  const background = runNotificationPoll("shared-poll", backgroundTask);

  expect(background).toBe(foreground);
  await Promise.resolve();
  finish();
  await foreground;
  await expect(runNotificationPoll("shared-poll", backgroundTask)).resolves.toBeUndefined();
  expect(backgroundTask).not.toHaveBeenCalled();
});

it("runs an overdue full sync after an empty poll and skips one after a recent sync", async () => {
  mockAuthedRequest.mockResolvedValue({ body: page([]) });
  expect(await refreshNativeNotifications("overdue-account", {} as never)).toBe(true);
  expect(mockSync).toHaveBeenCalledTimes(1);

  const revision = (await readNotificationState("recent-account"))!.pendingRevision;
  await finishNotificationSync("recent-account", revision, Date.now());
  expect(await refreshNativeNotifications("recent-account", {} as never)).toBe(false);
  expect(mockSync).toHaveBeenCalledTimes(1);
});

it("syncs while unlocked when SecureStore metadata cannot be read", async () => {
  mockSecureUnavailable = true;

  expect(await refreshNativeNotifications("unreadable-metadata", {} as never)).toBe(true);
  expect(mockSync).toHaveBeenCalledTimes(1);
});

it("does not let an old sync clear metadata after the same account signs back in", async () => {
  const userId = "wipe-resignin-sync";
  await recordNotificationPoll(userId, 1, true);
  const resolvers: Array<(value: unknown) => void> = [];
  mockSync.mockImplementation(() => new Promise((resolve) => resolvers.push(resolve)));
  const db = {} as never;
  const oldSync = runNativeSync(userId, db);
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  await clearNotificationState(userId);
  await resetNotificationState(userId);
  await recordNotificationPoll(userId, 9, true);
  const newSync = runNativeSync(userId, db);
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
  expect(mockSync).toHaveBeenCalledTimes(2);

  resolvers[0]({ sent: 0, failed: 0, remaining: 0, supersededUniqueIds: [] });
  await oldSync;
  expect(await readNotificationState(userId)).toMatchObject({ cursor: 9, pendingSync: true });

  resolvers[1]({ sent: 0, failed: 0, remaining: 0, supersededUniqueIds: [] });
  await newSync;
  expect(await readNotificationState(userId)).toMatchObject({ cursor: 9, pendingSync: false });
});
