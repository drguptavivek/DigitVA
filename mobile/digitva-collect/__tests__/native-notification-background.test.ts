const mockSecure = new Map<string, string>();
const mockAuthedRequest = jest.fn();
const mockAccounts = [{ user_id: "locked-account", name: "Must not be used" }];
let mockSecureUnavailable = false;
let mockAccountCounter = 0;

jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => {
    if (mockSecureUnavailable) throw new Error("device locked");
    return mockSecure.get(key) ?? null;
  }),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (mockSecureUnavailable) throw new Error("device locked");
    mockSecure.set(key, value);
  }),
  deleteItemAsync: jest.fn(async (key: string) => void mockSecure.delete(key)),
}));
jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: jest.fn(async (_algorithm: string, value: string) => `hash-${value}`),
}));
jest.mock("expo-background-task", () => ({
  BackgroundTaskResult: { Success: 1, Failed: 2 },
  registerTaskAsync: jest.fn(),
  unregisterTaskAsync: jest.fn(),
}));
jest.mock("expo-task-manager", () => ({
  defineTask: jest.fn(),
  getRegisteredTasksAsync: jest.fn(async () => []),
}));
jest.mock("react-native", () => ({
  Platform: { OS: "android" },
  NativeModules: {},
  TurboModuleRegistry: { get: () => null },
}));
jest.mock("../src/auth", () => ({
  authedRequest: (...args: unknown[]) => mockAuthedRequest(...args),
  loadAccounts: jest.fn(async () => mockAccounts),
  SessionRevokedError: class SessionRevokedError extends Error {},
  SignInRequiredError: class SignInRequiredError extends Error {},
}));
jest.mock("../src/interviewerDb", () => {
  throw new Error("background notification tasks must not import the encrypted database");
});

import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";
import { NATIVE_NOTIFICATION_TASK, runNativeNotificationTask, syncNotificationTaskRegistration } from "../src/notificationTask";
import { readNotificationState } from "../src/notificationState";

beforeEach(() => {
  mockSecure.clear();
  mockAuthedRequest.mockReset();
  mockSecureUnavailable = false;
  mockAccountCounter += 1;
  mockAccounts[0].user_id = `locked-account-${mockAccountCounter}`;
  (Platform as unknown as { OS: string }).OS = "android";
});

it("defines one module-scope task and stores only a pending cursor for a locked account", async () => {
  mockAuthedRequest.mockResolvedValue({
    body: {
      notifications: [{
        id: 7,
        kind: "case_reopened",
        created_at: "2026-10-05T09:30:00+00:00",
        project_id: "ABC01",
        death_id: null,
        draft_id: null,
        va_sid: null,
      }],
      next_cursor: 7,
    },
  });

  expect(TaskManager.defineTask).toHaveBeenCalledWith(NATIVE_NOTIFICATION_TASK, expect.any(Function));
  await runNativeNotificationTask();

  expect(mockAuthedRequest).toHaveBeenCalledWith(
    "locked-account-1",
    "/api/v1/me/notifications?after=0",
    { timeoutMs: 15_000 },
  );
  expect(await readNotificationState("locked-account-1")).toMatchObject({ cursor: 7, pendingSync: true });
});

it("exits without network access when SecureStore is unavailable", async () => {
  mockSecureUnavailable = true;

  await expect(runNativeNotificationTask()).resolves.toBeUndefined();
  expect(mockAuthedRequest).not.toHaveBeenCalled();
});

it("registers the inexact 15-minute Android worker and does not register elsewhere", async () => {
  await syncNotificationTaskRegistration(true);
  expect(BackgroundTask.registerTaskAsync).toHaveBeenCalledWith(NATIVE_NOTIFICATION_TASK, {
    minimumInterval: 15,
  });

  (Platform as unknown as { OS: string }).OS = "ios";
  await syncNotificationTaskRegistration(true);
  expect(BackgroundTask.registerTaskAsync).toHaveBeenCalledTimes(1);
});

it("does not define or register a background task on iOS", async () => {
  jest.resetModules();
  const { Platform: isolatedPlatform } = require("react-native") as typeof import("react-native");
  isolatedPlatform.OS = "ios";
  const isolatedTaskManager = require("expo-task-manager") as typeof TaskManager;
  const isolatedBackgroundTask = require("expo-background-task") as typeof BackgroundTask;
  const notificationTask = require("../src/notificationTask") as typeof import("../src/notificationTask");

  expect(isolatedTaskManager.defineTask).not.toHaveBeenCalled();
  await notificationTask.syncNotificationTaskRegistration(true);
  expect(isolatedBackgroundTask.registerTaskAsync).not.toHaveBeenCalled();
  expect(isolatedBackgroundTask.unregisterTaskAsync).not.toHaveBeenCalled();
});
