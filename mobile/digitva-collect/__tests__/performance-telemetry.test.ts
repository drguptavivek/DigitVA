import { Platform } from "react-native";

jest.mock("expo", () => ({
  requireOptionalNativeModule: () => null,
  default: {},
}));
const mockSecure = new Map<string, string>();
let mockSetError = false;
let mockDeleteError = false;
let mockGetError = false;
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => {
    if (mockGetError) throw new Error("secure store unavailable");
    return mockSecure.get(key) ?? null;
  }),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (mockSetError) throw new Error("secure store unavailable");
    mockSecure.set(key, value);
  }),
  deleteItemAsync: jest.fn(async (key: string) => {
    if (mockDeleteError) throw new Error("secure store unavailable");
    mockSecure.delete(key);
  }),
}));
jest.mock("expo-crypto", () => ({ randomUUID: jest.fn(() => "11111111-1111-4111-8111-111111111111") }));
jest.mock("../src/errorLog", () => ({
  setPerformanceCrashCounter: jest.fn(),
  setPerformanceErrorCounter: jest.fn(),
}));

import {
  __resetPerformanceTelemetryForTest,
  __sealTelemetryDayForTest,
  __seedTelemetryDayForTest,
  __telemetryStateForTest,
  flushPerformanceTelemetry,
  getPerformanceTelemetryEnabled,
  recordCrashMetric,
  recordErrorMetric,
  recordForegroundDuration,
  recordLaunch,
  setPerformanceTelemetryEnabled,
} from "../src/performanceTelemetry";

beforeEach(() => {
  mockSecure.clear();
  mockSetError = false;
  mockDeleteError = false;
  mockGetError = false;
  __resetPerformanceTelemetryForTest();
  Platform.OS = "android";
});

test("keeps bounded daily counters and produces a sealed immutable payload", async () => {
  recordLaunch();
  recordErrorMetric();
  recordCrashMetric();
  recordForegroundDuration(10_000);
  const day = new Date().toISOString().slice(0, 10);
  await __sealTelemetryDayForTest(day);
  const batch = __telemetryStateForTest().batches[0];
  expect(batch.payload.schema).toBe(1);
  expect(batch.payload.platform).toBe("android");
  expect(batch.payload.metrics).toEqual({ foreground_ms: 10_000, launches: 1, crashes: 1, errors: 1 });
  expect(JSON.stringify(batch.payload)).not.toMatch(/clinical|submission|user_id|route|model|location/i);
});

test("opt-out purges pending batches and prevents an upload", async () => {
  recordLaunch();
  await __sealTelemetryDayForTest(new Date().toISOString().slice(0, 10));
  await setPerformanceTelemetryEnabled(false);
  const send = jest.fn();
  await flushPerformanceTelemetry("user", send);
  expect(send).not.toHaveBeenCalled();
  expect(__telemetryStateForTest()).toEqual({ daily: {}, batches: [] });
});

test("uploads only the prior day with the fixed aggregate body and does not flush twice", async () => {
  const prior = new Date(Date.now() - 86_400_000).toISOString().slice(0, 10);
  await __seedTelemetryDayForTest(prior, { foreground_ms: 1, launches: 1, crashes: 0, errors: 0 });
  await __sealTelemetryDayForTest(prior);
  const send = jest.fn(async (_path: string, init: { method: "POST"; body: unknown }) => ({
    status: 200,
    body: { accepted: true, duplicate: false },
  }));
  await flushPerformanceTelemetry("user", send);
  await flushPerformanceTelemetry("user", send);
  expect(send).toHaveBeenCalledTimes(1);
  const [, init] = send.mock.calls[0];
  expect(init.method).toBe("POST");
  expect(Object.keys(init.body as object).sort()).toEqual([
    "app_version", "batch_id", "core_bucket", "day", "device_type", "manufacturer", "metrics", "platform", "ram_bucket", "schema", "variant",
  ].sort());
  expect(JSON.stringify(init.body)).not.toMatch(/clinical|submission|user_id|route|model|location/i);
});

test("does not send when a stored opt-out resolves during an access-refresh flush", async () => {
  __resetPerformanceTelemetryForTest(true);
  mockSecure.set("performance_telemetry_enabled", "false");
  const send = jest.fn();
  await flushPerformanceTelemetry("user", send);
  expect(send).not.toHaveBeenCalled();
  expect(__telemetryStateForTest()).toEqual({ daily: {}, batches: [] });
});

test("fails closed when the preference store cannot be read, then allows a retry", async () => {
  __resetPerformanceTelemetryForTest(true);
  mockGetError = true;
  expect(await getPerformanceTelemetryEnabled()).toBe(false);
  const send = jest.fn();
  await flushPerformanceTelemetry("user", send);
  expect(send).not.toHaveBeenCalled();
  mockGetError = false;
  expect(await getPerformanceTelemetryEnabled()).toBe(true);
});

test("merges a same-day stored cell field by field", async () => {
  __resetPerformanceTelemetryForTest(true);
  mockSecure.set("performance_telemetry_enabled", "true");
  const day = new Date().toISOString().slice(0, 10);
  mockSecure.set("performance_telemetry_daily", JSON.stringify({ [day]: { foreground_ms: 4, launches: 2, crashes: 3, errors: 5 } }));
  await getPerformanceTelemetryEnabled();
  recordLaunch();
  await __sealTelemetryDayForTest(day);
  expect(__telemetryStateForTest().batches[0].payload.metrics).toEqual({ foreground_ms: 4, launches: 3, crashes: 3, errors: 5 });
});

test("preference write failures reject while keeping collection disabled in memory", async () => {
  mockSetError = true;
  await expect(setPerformanceTelemetryEnabled(false)).rejects.toBeInstanceOf(Error);
  const send = jest.fn();
  await flushPerformanceTelemetry("user", send);
  expect(send).not.toHaveBeenCalled();
});

test("prunes old daily cells instead of blocking the queue forever", async () => {
  const now = new Date();
  const old = new Date(now.getTime() - 9 * 86_400_000).toISOString().slice(0, 10);
  const previous = new Date(now.getTime() - 86_400_000).toISOString().slice(0, 10);
  await __seedTelemetryDayForTest(old, { foreground_ms: 1, launches: 1, crashes: 0, errors: 0 });
  await __seedTelemetryDayForTest(previous, { foreground_ms: 1, launches: 1, crashes: 0, errors: 0 });
  recordLaunch();
  const state = __telemetryStateForTest();
  expect(Object.keys(state.daily).length).toBeLessThanOrEqual(2);
  expect(state.batches.every((batch) => batch.day !== old)).toBe(true);
});
