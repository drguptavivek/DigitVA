/**
 * Optional, aggregate-only app performance telemetry. This module deliberately has no
 * knowledge of forms, submissions, interviewers, routes or coding work.
 */
import * as SecureStore from "expo-secure-store";
import { randomUUID } from "expo-crypto";
import { AppState, Platform } from "react-native";
import { requireOptionalNativeModule } from "expo";

import { APP_VERSION } from "./appVersion";
import { isPlusVariant } from "./appVariant";
import { setPerformanceCrashCounter, setPerformanceErrorCounter } from "./errorLog";

const DAY_MS = 86_400_000;
const MAX_FOREGROUND_MS = DAY_MS;
const MAX_BATCHES = 2;
const MAX_DAILY_COUNT = 1_000;
const MAX_BATCH_AGE_DAYS = 7;
const MAX_BODY_BYTES = 8_192;
const ENABLED_KEY = "performance_telemetry_enabled";
const DAILY_KEY = "performance_telemetry_daily";
const BATCHES_KEY = "performance_telemetry_batches";
const FLUSH_DAY_KEY = "performance_telemetry_flush_day";
const OPTIONS: SecureStore.SecureStoreOptions = { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY };

type Metrics = { foreground_ms: number; launches: number; crashes: number; errors: number };
type Daily = { day: string; metrics: Metrics };
type HardwareProfile = {
  device_type: "phone" | "tablet" | "emulator" | "other";
  ram_bucket: "unknown" | "lt2" | "2_3" | "4_5" | "6_7" | "8_11" | "12plus";
  core_bucket: "unknown" | "1_2" | "3_4" | "5_8" | "9plus";
  manufacturer: "unknown" | "samsung" | "google" | "xiaomi" | "oneplus" | "motorola" | "oppo" | "vivo" | "apple" | "other";
};
export interface PerformancePayload {
  schema: 1;
  batch_id: string;
  day: string;
  app_version: string;
  variant: "collect" | "plus";
  platform: "android";
  device_type: HardwareProfile["device_type"];
  ram_bucket: HardwareProfile["ram_bucket"];
  core_bucket: HardwareProfile["core_bucket"];
  manufacturer: HardwareProfile["manufacturer"];
  metrics: Metrics;
}
type Batch = { day: string; payload: PerformancePayload };
type SendBatch = (path: string, init: { method: "POST"; body: unknown }) => Promise<{ status: number; body: unknown }>;

const emptyMetrics = (): Metrics => ({ foreground_ms: 0, launches: 0, crashes: 0, errors: 0 });
const today = (): string => new Date().toISOString().slice(0, 10);
const previousDay = (day: string): string => new Date(Date.parse(`${day}T00:00:00.000Z`) - DAY_MS).toISOString().slice(0, 10);
const safeInteger = (value: unknown, max = Number.MAX_SAFE_INTEGER): number =>
  typeof value === "number" && Number.isFinite(value) ? Math.max(0, Math.min(max, Math.round(value))) : 0;
const monotonicNow = (): number => {
  try {
    if (typeof performance !== "undefined" && typeof performance.now === "function") return performance.now();
  } catch {
    // Older runtimes may not expose the Performance API.
  }
  return Date.now();
};

let enabled = true;
let enabledLoaded = false;
let enabledRead: Promise<boolean> | undefined;
let preferenceGeneration = 0;
let stateLoaded = false;
let loading: Promise<void> | undefined;
let daily: Record<string, Metrics> = {};
let batches: Batch[] = [];
let persistTimer: ReturnType<typeof setTimeout> | undefined;
let lifecycleInstalled = false;
let foregroundStartedAt: number | undefined;
let foregroundDay: string | undefined;
let flushDay: string | undefined;
let storageWrites: Promise<void> = Promise.resolve();
let purgePending = false;

const nativeInfo = (): { getHardwareProfile?: () => HardwareProfile } | null => {
  if (Platform.OS !== "android") return null;
  try {
    return requireOptionalNativeModule<{ getHardwareProfile?: () => HardwareProfile }>("DigitvaDeviceInfo");
  } catch {
    return null;
  }
};

function defaultHardware(): HardwareProfile {
  return { device_type: "other", ram_bucket: "unknown", core_bucket: "unknown", manufacturer: "unknown" };
}

function hardware(): HardwareProfile {
  try {
    const value = nativeInfo()?.getHardwareProfile?.();
    if (!value) return defaultHardware();
    return {
      device_type: ["phone", "tablet", "emulator", "other"].includes(value.device_type) ? value.device_type : "other",
      ram_bucket: ["unknown", "lt2", "2_3", "4_5", "6_7", "8_11", "12plus"].includes(value.ram_bucket) ? value.ram_bucket : "unknown",
      core_bucket: ["unknown", "1_2", "3_4", "5_8", "9plus"].includes(value.core_bucket) ? value.core_bucket : "unknown",
      manufacturer: ["unknown", "samsung", "google", "xiaomi", "oneplus", "motorola", "oppo", "vivo", "apple", "other"].includes(value.manufacturer) ? value.manufacturer : "unknown",
    };
  } catch {
    return defaultHardware();
  }
}

function appVersion(): string {
  return /^(\d+\.\d+\.\d+)/.exec(APP_VERSION)?.[1] ?? "0.0.0";
}

function schedulePersist(): void {
  if (!enabledLoaded || !enabled || persistTimer !== undefined) return;
  persistTimer = setTimeout(() => {
    persistTimer = undefined;
    void persistState();
  }, 250);
}

function queueStorageWrite(task: () => Promise<void>): Promise<void> {
  const result = storageWrites.then(task, task);
  storageWrites = result.catch(() => undefined);
  return result;
}

async function readJson<T>(key: string): Promise<T | undefined> {
  try {
    const raw = await SecureStore.getItemAsync(key, OPTIONS);
    return raw ? JSON.parse(raw) as T : undefined;
  } catch {
    return undefined;
  }
}

/** Preference reads are security-sensitive: missing means default-on, but an unavailable/corrupt value fails closed. */
async function readTelemetryPreference(): Promise<{ ok: true; value?: boolean } | { ok: false }> {
  try {
    const raw = await SecureStore.getItemAsync(ENABLED_KEY, OPTIONS);
    if (!raw) return { ok: true };
    const value: unknown = JSON.parse(raw);
    return typeof value === "boolean" ? { ok: true, value } : { ok: false };
  } catch {
    return { ok: false };
  }
}

async function ensureState(): Promise<void> {
  if (!(await getPerformanceTelemetryEnabled())) return;
  if (stateLoaded) return;
  if (loading) return loading;
  loading = (async () => {
    const [savedDaily, savedBatches, savedFlushDay] = await Promise.all([
      readJson<Record<string, Metrics>>(DAILY_KEY),
      readJson<Batch[]>(BATCHES_KEY),
      readJson<string>(FLUSH_DAY_KEY),
    ]);
    if (savedDaily && typeof savedDaily === "object") {
      for (const [day, saved] of Object.entries(savedDaily)) {
        const current = daily[day] ?? emptyMetrics();
        daily[day] = {
          foreground_ms: safeInteger(current.foreground_ms + safeInteger(saved?.foreground_ms), MAX_FOREGROUND_MS),
          launches: safeInteger(current.launches + safeInteger(saved?.launches), MAX_DAILY_COUNT),
          crashes: safeInteger(current.crashes + safeInteger(saved?.crashes), MAX_DAILY_COUNT),
          errors: safeInteger(current.errors + safeInteger(saved?.errors), MAX_DAILY_COUNT),
        };
      }
    }
    if (Array.isArray(savedBatches)) batches = [...savedBatches, ...batches].slice(-MAX_BATCHES);
    if (typeof savedFlushDay === "string") flushDay = savedFlushDay;
    stateLoaded = true;
    loading = undefined;
    pruneDaily(today());
  })();
  return loading;
}

async function persistState(): Promise<void> {
  if (!enabledLoaded || !enabled) return;
  const generation = preferenceGeneration;
  const savedDaily = JSON.stringify(daily);
  const savedBatches = JSON.stringify(batches);
  await queueStorageWrite(async () => {
    if (!enabledLoaded || !enabled || generation !== preferenceGeneration) return;
    await SecureStore.setItemAsync(DAILY_KEY, savedDaily, OPTIONS);
    if (!enabledLoaded || !enabled || generation !== preferenceGeneration) return;
    await SecureStore.setItemAsync(BATCHES_KEY, savedBatches, OPTIONS);
  }).catch(() => undefined);
}

function metric(day: string, field: keyof Metrics, amount: number): void {
  if (!enabledLoaded) {
    void getPerformanceTelemetryEnabled();
    return;
  }
  if (!enabled) return;
  if (!stateLoaded) void ensureState();
  const next = daily[day] ?? emptyMetrics();
  next[field] = safeInteger(next[field] + amount, field === "foreground_ms" ? MAX_FOREGROUND_MS : MAX_DAILY_COUNT);
  daily[day] = next;
  pruneDaily(today());
  schedulePersist();
}

export function recordLaunch(): void { metric(today(), "launches", 1); }
export function recordErrorMetric(): void { metric(today(), "errors", 1); }
export function recordCrashMetric(): void { metric(today(), "crashes", 1); }
export function recordForegroundDuration(milliseconds: number): void { metric(today(), "foreground_ms", milliseconds); }

function settleForeground(now = monotonicNow()): void {
  if (foregroundStartedAt === undefined || !foregroundDay) return;
  const elapsed = Math.max(0, now - foregroundStartedAt);
  if (foregroundDay === today()) metric(foregroundDay, "foreground_ms", elapsed);
  else metric(foregroundDay, "foreground_ms", Math.min(elapsed, MAX_FOREGROUND_MS));
  foregroundStartedAt = undefined;
  foregroundDay = undefined;
}

function startForeground(): void {
  if (!enabledLoaded || !enabled || foregroundStartedAt !== undefined) return;
  foregroundStartedAt = monotonicNow();
  foregroundDay = today();
}

/** Install the low-cost foreground counter once. It never starts a request or waits on storage. */
export function installPerformanceTelemetryLifecycle(): () => void {
  if (lifecycleInstalled || Platform.OS !== "android") return () => undefined;
  lifecycleInstalled = true;
  setPerformanceErrorCounter(recordErrorMetric);
  setPerformanceCrashCounter(recordCrashMetric);
  // Resolve the visible opt-out before recording anything; a stored opt-out must not create a speculative cell.
  void getPerformanceTelemetryEnabled().then((allowed) => {
    if (!allowed || !lifecycleInstalled) return;
    recordLaunch();
    if (AppState.currentState === "active") startForeground();
  });
  const subscription = AppState.addEventListener("change", (next) => {
    if (next === "active") startForeground();
    else settleForeground();
  });
  return () => {
    settleForeground();
    subscription.remove();
    setPerformanceErrorCounter(undefined);
    setPerformanceCrashCounter(undefined);
    lifecycleInstalled = false;
  };
}

function dayAge(day: string, referenceDay: string): number {
  return Math.floor((Date.parse(`${referenceDay}T00:00:00.000Z`) - Date.parse(`${day}T00:00:00.000Z`)) / DAY_MS);
}

/** Keep only today/yesterday in the aggregate journal; older values are sealed when possible, otherwise dropped. */
function pruneDaily(referenceDay: string): void {
  if (!enabledLoaded || !enabled) return;
  let changed = false;
  const staleBatches = batches.filter((batch) => dayAge(batch.day, referenceDay) <= MAX_BATCH_AGE_DAYS);
  if (staleBatches.length !== batches.length) {
    batches = staleBatches;
    changed = true;
  }
  const previous = previousDay(referenceDay);
  for (const day of Object.keys(daily).sort()) {
    if (day === referenceDay || day === previous) continue;
    if (dayAge(day, referenceDay) > MAX_BATCH_AGE_DAYS) {
      delete daily[day];
      changed = true;
      continue;
    }
    // A sealed batch is immutable; if the two-slot queue is full the old cell is best-effort dropped.
    seal(day);
    delete daily[day];
    changed = true;
  }
  if (changed) schedulePersist();
}

function seal(day: string): void {
  if (batches.some((batch) => batch.day === day) || batches.length >= MAX_BATCHES) return;
  const metrics = daily[day];
  if (!metrics) return;
  const payload: PerformancePayload = {
    schema: 1,
    batch_id: randomUUID(),
    day,
    app_version: appVersion(),
    variant: isPlusVariant() ? "plus" : "collect",
    platform: "android",
    ...hardware(),
    metrics: {
      foreground_ms: safeInteger(metrics.foreground_ms, MAX_FOREGROUND_MS),
      launches: safeInteger(metrics.launches, MAX_DAILY_COUNT),
      crashes: safeInteger(metrics.crashes, MAX_DAILY_COUNT),
      errors: safeInteger(metrics.errors, MAX_DAILY_COUNT),
    },
  };
  if (JSON.stringify(payload).length > MAX_BODY_BYTES) return;
  batches.push({ day, payload });
  delete daily[day];
  schedulePersist();
}

/** Flush at most once per calendar day. The caller supplies the existing authenticated transport. */
export async function flushPerformanceTelemetry(_userId: string, send: SendBatch): Promise<void> {
  if (Platform.OS !== "android" || !(await getPerformanceTelemetryEnabled())) return;
  await ensureState();
  if (!(await getPerformanceTelemetryEnabled())) return;
  const day = today();
  if (flushDay === day) return;
  seal(previousDay(day));
  flushDay = day;
  await queueStorageWrite(async () => {
    if (enabledLoaded && enabled) await SecureStore.setItemAsync(FLUSH_DAY_KEY, day, OPTIONS);
  }).catch(() => undefined);
  for (const batch of [...batches]) {
    if (!(await getPerformanceTelemetryEnabled())) return;
    if (batch.day >= day) continue;
    try {
      const reply = await send("/api/v1/analytics/app/batches", { method: "POST", body: batch.payload });
      const body = reply.body as { accepted?: unknown };
      if (reply.status >= 200 && reply.status < 300 && body?.accepted === true) {
        batches = batches.filter((candidate) => candidate.payload.batch_id !== batch.payload.batch_id);
        schedulePersist();
      }
    } catch {
      // 503/network failures keep the sealed, immutable batch for a later day.
    }
  }
}

export async function getPerformanceTelemetryEnabled(): Promise<boolean> {
  if (enabledLoaded) return enabled;
  if (enabledRead) return enabledRead;
  const generation = preferenceGeneration;
  enabledRead = (async () => {
    const preference = await readTelemetryPreference();
    if (generation === preferenceGeneration) {
      enabled = preference.ok && preference.value !== false;
      // A failed read remains retryable; callers still receive false while this process is fail-closed.
      enabledLoaded = preference.ok;
      if (!enabled) {
        daily = {};
        batches = [];
        if (persistTimer !== undefined) clearTimeout(persistTimer);
        persistTimer = undefined;
        void queueStorageWrite(async () => {
          await SecureStore.deleteItemAsync(DAILY_KEY, OPTIONS);
          await SecureStore.deleteItemAsync(BATCHES_KEY, OPTIONS);
          await SecureStore.deleteItemAsync(FLUSH_DAY_KEY, OPTIONS);
        }).catch(() => undefined);
      }
    }
    const result = enabled;
    enabledRead = undefined;
    return result;
  })();
  return enabledRead;
}

export async function setPerformanceTelemetryEnabled(next: boolean): Promise<void> {
  preferenceGeneration += 1;
  enabled = false;
  enabledLoaded = true;
  enabledRead = undefined;
  if (!next) {
    daily = {};
    batches = [];
    flushDay = undefined;
    if (persistTimer !== undefined) clearTimeout(persistTimer);
    persistTimer = undefined;
    await queueStorageWrite(async () => {
      let firstError: unknown;
      try {
        await SecureStore.setItemAsync(ENABLED_KEY, "false", OPTIONS);
      } catch (error) {
        firstError = error;
      } finally {
        for (const key of [DAILY_KEY, BATCHES_KEY, FLUSH_DAY_KEY]) {
          try {
            await SecureStore.deleteItemAsync(key, OPTIONS);
          } catch (error) {
            firstError ??= error;
          }
        }
      }
      if (firstError) {
        purgePending = true;
        throw firstError;
      }
      purgePending = false;
    });
    return;
  }
  if (purgePending) {
    await queueStorageWrite(async () => {
      for (const key of [DAILY_KEY, BATCHES_KEY, FLUSH_DAY_KEY]) await SecureStore.deleteItemAsync(key, OPTIONS);
      purgePending = false;
    });
  }
  await queueStorageWrite(() => SecureStore.setItemAsync(ENABLED_KEY, "true", OPTIONS));
  enabled = true;
}

/** Test seam for payload shape and sealed retry behaviour; production callers do not need it. */
export function __telemetryStateForTest(): { daily: Record<string, Metrics>; batches: Batch[] } {
  return { daily: JSON.parse(JSON.stringify(daily)), batches: JSON.parse(JSON.stringify(batches)) };
}

export async function __sealTelemetryDayForTest(day: string): Promise<void> {
  await ensureState();
  seal(day);
}

export async function __seedTelemetryDayForTest(day: string, metrics: Metrics = emptyMetrics()): Promise<void> {
  await ensureState();
  daily[day] = { ...metrics };
}

export function __resetPerformanceTelemetryForTest(readPreference = false): void {
  if (persistTimer !== undefined) clearTimeout(persistTimer);
  persistTimer = undefined;
  enabled = true;
  enabledLoaded = !readPreference;
  enabledRead = undefined;
  preferenceGeneration += 1;
  stateLoaded = !readPreference;
  loading = undefined;
  daily = {};
  batches = [];
  flushDay = undefined;
  foregroundStartedAt = undefined;
  foregroundDay = undefined;
  purgePending = false;
  setPerformanceErrorCounter(undefined);
  setPerformanceCrashCounter(undefined);
}
