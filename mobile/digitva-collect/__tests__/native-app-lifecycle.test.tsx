import React, { useEffect } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { AppState } from "react-native";

const mockAppStateListeners = new Set<(state: string) => void>();
const mockRouter = { replace: jest.fn() };
const mockSecure = new Map<string, string>();
const mockSave = jest.fn(async () => undefined);
const mockLockAll = jest.fn(async (..._args: unknown[]) => undefined);
const mockOpenDb = jest.fn(async (..._args: unknown[]) => ({}) as never);
const mockRefresh = jest.fn(async (..._args: unknown[]) => undefined);
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
  loadDevice: jest.fn(async () => ({ device_id: "d", server: "https://example.test", project_id: "p", project_name: "P" })),
  loadAccounts: jest.fn(async () => [{ user_id: "worker", name: "Worker" }]),
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

import { AppStateProvider, useAppState } from "../src/AppState";

function Probe() {
  const state = useAppState();
  useEffect(() => state.onBeforeLock(mockSave), [state.onBeforeLock]);
  return <>{JSON.stringify({ ready: state.ready, accounts: state.accounts.length, lockVersion: state.lockVersion, error: state.error })}</>;
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
  mockSave.mockReset();
  mockSave.mockResolvedValue(undefined);
  mockLockAll.mockClear();
  mockOpenDb.mockClear();
  mockRefresh.mockClear();
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
