import React, { useEffect } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { AppState } from "react-native";

const mockAppStateListeners = new Set<(state: string) => void>();
const mockRouter = { replace: jest.fn() };
const mockSecure = new Map<string, string>();
const mockAccounts = [{ user_id: "worker", name: "Worker", server: "https://example.test", collection_access: true }];
const mockSave = jest.fn(async () => undefined);
const mockLockAll = jest.fn(async (..._args: unknown[]) => undefined);
const mockOpenDb = jest.fn(async (..._args: unknown[]) => ({}) as never);
const mockRefresh = jest.fn(async (..._args: unknown[]) => undefined);
const mockNotificationRefresh = jest.fn(async (..._args: unknown[]) => false);
const mockReconcile = jest.fn(async (..._args: unknown[]) => undefined);
let mockAutoLockCallback: (() => void) | undefined;
let mockAccessListener: ((userId: string, access: unknown) => Promise<void> | void) | undefined;

jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockSecure.set(key, value)),
}));
jest.mock("../src/autoLock", () => ({
  createAutoLock: (callback: () => void) => {
    mockAutoLockCallback = callback;
    return { activity: jest.fn(), appStateChanged: jest.fn(), stop: jest.fn() };
  },
}));
jest.mock("../src/i18n", () => ({ setUiLocale: () => "en" }));
jest.mock("../src/ui", () => ({ errorText: (error: unknown) => `error:${String(error)}` }));
jest.mock("../src/auth", () => ({
  loadActiveSlot: jest.fn(async () => "active"),
  setActiveSlot: jest.fn(async () => undefined),
  loadDevice: jest.fn(async () => ({ device_id: "d", server: "https://example.test", project_id: "p", project_name: "P" })),
  loadAccounts: jest.fn(async () => mockAccounts.map((account) => ({ ...account }))),
  standaloneModeAvailable: jest.fn(async () => false),
  subscribeAccountChanges: jest.fn(() => () => undefined),
  subscribeAccessChanges: jest.fn((listener: typeof mockAccessListener) => {
    mockAccessListener = listener ?? undefined;
    return () => { mockAccessListener = undefined; };
  }),
}));
jest.mock("../src/interviewerDb", () => ({
  anyUnlocked: () => true,
  isUnlocked: () => true,
  lockAll: (...args: unknown[]) => mockLockAll(...args),
  openInterviewerDb: (...args: unknown[]) => mockOpenDb(...args),
}));
jest.mock("../src/sync", () => ({
  refreshReferenceData: (...args: unknown[]) => mockRefresh(...args),
  reconcileReferenceAccess: (...args: unknown[]) => mockReconcile(...args),
}));
jest.mock("../src/nativeNotificationSync", () => ({
  refreshNativeNotifications: (...args: unknown[]) => mockNotificationRefresh(...args),
  runNativeSync: jest.fn(async () => ({ sync: {}, reference: undefined })),
}));

import { AppStateProvider, useAppState } from "../src/AppState";
import { recordServerDate, resetPhoneClock } from "../src/phoneClock";

let latest!: ReturnType<typeof useAppState>;

function Probe() {
  const state = useAppState();
  latest = state;
  useEffect(() => state.onBeforeLock(mockSave), [state.onBeforeLock]);
  return <>{JSON.stringify({ ready: state.ready, accounts: state.accounts.length, lockVersion: state.lockVersion, error: state.error, background: state.backgroundError })}</>;
}

async function renderProbe(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AppStateProvider><Probe /></AppStateProvider>);
  });
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  await act(async () => {
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  return tree;
}

beforeEach(() => {
  mockSecure.clear();
  mockAccounts[0].collection_access = true;
  mockSave.mockReset();
  mockSave.mockResolvedValue(undefined);
  mockLockAll.mockClear();
  mockOpenDb.mockClear();
  mockRefresh.mockClear();
  mockNotificationRefresh.mockClear();
  mockReconcile.mockClear();
  mockAppStateListeners.clear();
  mockAutoLockCallback = undefined;
  mockAccessListener = undefined;
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "background" });
  jest.spyOn(AppState, "addEventListener").mockImplementation((_event, listener) => {
    mockAppStateListeners.add(listener as (state: string) => void);
    return { remove: () => mockAppStateListeners.delete(listener as (state: string) => void) } as never;
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

it("flushes the registered form hook before foreground refresh and reconciles revoked scope without another fetch", async () => {
  const tree = await renderProbe();
  expect(String(tree.toJSON())).toContain('"accounts":1');
  await act(async () => {
    for (const listener of [...mockAppStateListeners]) listener("background");
    for (const listener of [...mockAppStateListeners]) listener("active");
    await Promise.resolve();
  });
  await act(async () => {
    for (const listener of [...mockAppStateListeners]) listener("background");
    for (const listener of [...mockAppStateListeners]) listener("active");
    await new Promise<void>((resolve) => setTimeout(resolve, 20));
  });
  expect(mockSave).toHaveBeenCalled();
  expect(mockOpenDb).toHaveBeenCalled();
  expect(mockRefresh).toHaveBeenCalledWith("worker", expect.anything(), { force: true });

  await act(async () => {
    await mockAccessListener?.("worker", { projects: [] });
  });
  expect(mockSave.mock.calls.length).toBeGreaterThanOrEqual(2);
  expect(mockReconcile).toHaveBeenCalledWith(expect.anything(), { projects: [] });
  await act(async () => tree.unmount());
});

it("does not refresh collection reference data for a role-only account", async () => {
  mockAccounts[0].collection_access = false;
  const tree = await renderProbe();

  await act(async () => {
    for (const listener of [...mockAppStateListeners]) listener("background");
    for (const listener of [...mockAppStateListeners]) listener("active");
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });

  expect(mockRefresh).not.toHaveBeenCalled();
  expect(mockNotificationRefresh).toHaveBeenCalledWith("worker", expect.anything());
  await act(async () => tree.unmount());
});

it("surfaces a save failure and aborts both foreground refresh and locking", async () => {
  const tree = await renderProbe();
  mockSave.mockRejectedValue(new Error("save failed"));
  await act(async () => {
    for (const listener of [...mockAppStateListeners]) listener("background");
    for (const listener of [...mockAppStateListeners]) listener("active");
    await Promise.resolve();
  });
  await act(async () => {
    for (const listener of [...mockAppStateListeners]) listener("background");
    for (const listener of [...mockAppStateListeners]) listener("active");
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  expect(mockRefresh).not.toHaveBeenCalled();
  expect(String(tree.toJSON())).toContain("error:Error: save failed");

  mockSave.mockRejectedValue(new Error("save failed again"));
  await act(async () => {
    await mockAutoLockCallback?.();
  });
  expect(mockLockAll).not.toHaveBeenCalled();
  expect(String(tree.toJSON())).toContain("error:Error: save failed again");
  await act(async () => tree.unmount());
});

it("surfaces a database close failure and keeps the app locked operation retryable", async () => {
  const tree = await renderProbe();
  mockLockAll.mockRejectedValue(new Error("close failed"));

  await act(async () => {
    await mockAutoLockCallback?.();
  });

  expect(mockLockAll).toHaveBeenCalledTimes(1);
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(String(tree.toJSON())).toContain("error:Error: close failed");
  await act(async () => tree.unmount());
});

it("marks only a revoked or sign-in-required failure as blocking; other lock failures are generic", async () => {
  const { SessionRevokedError, SignInRequiredError } = jest.requireActual("../src/authErrors");
  const tree = await renderProbe();
  mockLockAll.mockRejectedValueOnce(new Error("close failed"));
  await act(async () => { await mockAutoLockCallback?.(); });
  expect(latest.error).toContain("close failed");
  expect(latest.errorBlocking).toBe(false);
  mockLockAll.mockRejectedValueOnce(new SessionRevokedError());
  await act(async () => { await mockAutoLockCallback?.(); });
  expect(latest.errorBlocking).toBe(true);
  await act(async () => latest.clearError());
  expect(latest.error).toBeUndefined();
  expect(latest.errorBlocking).toBe(false);
  mockLockAll.mockRejectedValueOnce(new SignInRequiredError());
  await act(async () => { await mockAutoLockCallback?.(); });
  expect(latest.errorBlocking).toBe(true);
  await act(async () => tree.unmount());
});

const SETTLE = () => act(async () => { await new Promise<void>((resolve) => setTimeout(resolve, 0)); });

it("an unchanged poll and an unchanged access result change no state", async () => {
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  const tree = await renderProbe();
  await SETTLE();
  const before = { accounts: latest.accounts, lockVersion: latest.lockVersion };
  await act(async () => { await mockAccessListener?.("worker", { projects: [] }); });
  const afterFirst = latest.lockVersion;
  expect(afterFirst).toBe(before.lockVersion + 1);
  await act(async () => { await mockAccessListener?.("worker", { projects: [] }); });
  await act(async () => { await latest.reload(); });
  expect(mockReconcile).toHaveBeenCalledTimes(1);
  expect(latest.lockVersion).toBe(afterFirst);
  expect(latest.accounts).toBe(before.accounts);
  await act(async () => tree.unmount());
});

it("a changed access result waits for the open form to be left", async () => {
  const tree = await renderProbe();
  let release!: () => void;
  await act(async () => { release = latest.holdRefresh!(); });
  const before = latest.lockVersion;
  await act(async () => { await mockAccessListener?.("worker", { projects: [] }); });
  expect(mockReconcile).toHaveBeenCalledTimes(1);
  expect(latest.lockVersion).toBe(before);
  await act(async () => release());
  expect(latest.lockVersion).toBe(before + 1);
  await act(async () => tree.unmount());
});

describe("background failures", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("show a banner instead of the gate and back off the poll", async () => {
    Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
    let tree!: ReactTestRenderer;
    await act(async () => { tree = create(<AppStateProvider><Probe /></AppStateProvider>); });
    await act(async () => { await jest.advanceTimersByTimeAsync(0); });
    mockNotificationRefresh.mockReset();
    mockNotificationRefresh.mockRejectedValue(new Error("down"));
    const polls = () => mockNotificationRefresh.mock.calls.length;
    await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
    expect(polls()).toBe(1);
    expect(latest.error).toBeUndefined();
    expect(latest.backgroundError).toContain("down");
    await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
    expect(polls()).toBe(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
    expect(polls()).toBe(2);
    mockNotificationRefresh.mockResolvedValue(false);
    await act(async () => { await jest.advanceTimersByTimeAsync(240_000); });
    expect(latest.backgroundError).toBeUndefined();
    await act(async () => tree.unmount());
  });
});

it("saves the open form the moment the phone clock passes 4 hours off, and not for a small offset", async () => {
  const tree = await renderProbe();
  mockSave.mockClear();
  await act(async () => {
    recordServerDate(new Date(0).toUTCString(), 120_000);
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  expect(mockSave).not.toHaveBeenCalled();
  await act(async () => {
    recordServerDate(new Date(0).toUTCString(), 5 * 3600_000);
    await new Promise<void>((resolve) => setTimeout(resolve, 0));
  });
  expect(mockSave).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
  resetPhoneClock();
});

describe("offline gate", () => {
  const network = () => jest.requireActual("../src/network") as typeof import("../src/network");
  const emit = async (state: { isConnected: boolean; isInternetReachable: boolean | null }) => {
    const mock = (require("expo-network").addNetworkStateListener as jest.Mock).mock;
    await act(async () => mock.calls[mock.calls.length - 1][0](state));
  };

  afterEach(() => {
    network().resetNetwork();
    jest.useRealTimers();
  });

  it("shows offline and runs one debounced sync on reconnect, even through a flapping connection", async () => {
    const { runNativeSync } = require("../src/nativeNotificationSync") as { runNativeSync: jest.Mock };
    runNativeSync.mockClear();
    const tree = await renderProbe();
    jest.useFakeTimers();
    await emit({ isConnected: false, isInternetReachable: false });
    expect(latest.offline).toBe(true);
    await emit({ isConnected: true, isInternetReachable: true });
    await emit({ isConnected: false, isInternetReachable: false });
    await emit({ isConnected: true, isInternetReachable: true });
    expect(latest.offline).toBe(false);
    expect(runNativeSync).not.toHaveBeenCalled();
    await act(async () => { await jest.advanceTimersByTimeAsync(2_100); });
    expect(runNativeSync).toHaveBeenCalledTimes(1);
    await act(async () => tree.unmount());
  });

  it("unknown reachability is online", async () => {
    const tree = await renderProbe();
    await emit({ isConnected: true, isInternetReachable: null });
    expect(latest.offline).toBe(false);
    expect(() => network().assertOnline()).not.toThrow();
    await act(async () => tree.unmount());
  });
});
