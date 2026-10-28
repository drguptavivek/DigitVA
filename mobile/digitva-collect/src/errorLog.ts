/**
 * The phone's local error log (docs/policy/expo-client.md, "Local error log"). An entry is the same content as
 * the on-screen Ref line: status, code, method and masked route, or the native function and cause. Never
 * answers, names, tokens, phone numbers or server free text. Entries wait in a small memory buffer until an
 * interviewer's encrypted store is open (src/errorLogDb.ts writes them there); nothing is written in plaintext.
 */
import { Platform } from "react-native";

import { ApiError } from "./api";
import { APP_VERSION } from "./appVersion";
import { uiTextKnown } from "./i18n";
import { networkSpell, OfflineError } from "./network";

export interface ErrorEntry {
  at: string;
  appVersion: string;
  route: string;
  what: string;
  device: string;
  android: string;
}

export const MAX_ERRORS = 500;
export const MAX_ERROR_AGE_DAYS = 30;
/** Entries held in memory while the store is locked; the oldest are dropped. */
const BUFFER_MAX = 50;
/** The same error on the same screen within this window is one entry (a render calling errorText twice). */
const DUPLICATE_MS = 60_000;
/** A toast right after an errorText call shows that error again; not a second entry. */
const TOAST_ECHO_MS = 2_000;

type Writer = (entries: ErrorEntry[]) => Promise<boolean>;
type Counter = () => void;

let route = "";
let writer: Writer | undefined;
let flushing = false;
let lastRecordedAt = 0;
/** The network spell a "network" failure was last filed in: one entry per spell, not per attempt. */
let networkLoggedSpell = -1;
let performanceErrorCounter: Counter | undefined;
let performanceCrashCounter: Counter | undefined;
const buffer: ErrorEntry[] = [];
const lastSeen = new Map<string, number>();

/** The screen errors are filed under (a pathname such as "/worklist"; params never included). */
export function setErrorRoute(pathname: string): void {
  route = pathname.slice(0, 60);
}

/** Install (or remove) the function that stores entries; it resolves false while no store is open. */
export function setErrorWriter(next: Writer | undefined): void {
  writer = next;
}

/** Optional aggregate-only hook. The callback receives no error text or other diagnostic data. */
export function setPerformanceErrorCounter(next: Counter | undefined): void {
  performanceErrorCounter = next;
}

/** Optional aggregate-only hook for the app's fatal-error handler. */
export function setPerformanceCrashCounter(next: Counter | undefined): void {
  performanceCrashCounter = next;
}

/** Record one sanitized fatal event without retaining its message, stack, route or payload. */
export function recordPerformanceCrash(): void {
  try {
    performanceCrashCounter?.();
  } catch {
    // Diagnostics must never throw into the fatal-error path.
  }
}

/** Entries not stored yet (the store is locked); the export includes them. */
export const pendingErrors = (): ErrorEntry[] => [...buffer];

/** Test hook: forget every buffered entry and the duplicate guard. */
export function resetErrorLog(): void {
  buffer.length = 0;
  lastSeen.clear();
  lastRecordedAt = 0;
  networkLoggedSpell = -1;
  route = "";
  flushing = false;
  performanceErrorCounter = undefined;
  performanceCrashCounter = undefined;
}

/**
 * The scrubbed description of a failure: the middle of the Ref line. Quoted text is masked unless it is a bare
 * identifier path (a native function name such as 'NativeDatabase.prepareAsync'); unquoted file paths are
 * masked; "code 5" survives (under 4 digits).
 */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return [`HTTP ${error.status}`, error.code, error.path && `${error.method ?? "GET"} ${error.path}`].filter(Boolean).join(" ");
  }
  if (error instanceof OfflineError) return "offline";
  if (error instanceof TypeError) return "network";
  if (error instanceof Error) {
    const msg = error.message
      .replace(/(["'`])(.*?)\1/g, (_, q, body) => (/^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$/.test(body) && body.length <= 60 ? q + body + q : `${q}…${q}`))
      .replace(/(file:\/\/|\/data\/)[^\s"'`]*/g, "file:…")
      .replace(/\d{4,}/g, "#")
      .replace(/\s+/g, " ")
      .slice(0, 160);
    return `${error.name} ${msg}`.trim();
  }
  return "unknown";
}

function deviceInfo(): { device: string; android: string } {
  const constants = (Platform.constants ?? {}) as { Brand?: string; Model?: string; Release?: string };
  return { device: [constants.Brand, constants.Model].filter(Boolean).join(" ") || "unknown", android: constants.Release ?? "unknown" };
}

/** File one error. Fire and forget: logging must never throw into the code that reports the error. */
export function recordError(what: string): void {
  const now = Date.now();
  const at = new Date(now).toISOString();
  const key = `${route}|${what}`;
  const duplicate = now - (lastSeen.get(key) ?? 0) < DUPLICATE_MS;
  lastRecordedAt = now;
  // Offline is a known state, not a fault; a real network failure is filed once per offline spell.
  if (what === "offline") return;
  if (what === "network") {
    if (networkLoggedSpell === networkSpell()) return;
    networkLoggedSpell = networkSpell();
  }
  if (duplicate) return;
  try {
    performanceErrorCounter?.();
  } catch {
    // Diagnostics must never throw into the error path.
  }
  if (lastSeen.size > 100) lastSeen.clear();
  lastSeen.set(key, now);
  buffer.push({ at, appVersion: APP_VERSION, route, what: what.slice(0, 200), ...deviceInfo() });
  if (buffer.length > BUFFER_MAX) buffer.shift();
  void flushErrors();
}

/** An error toast that did not come through errorText: filed only when its text is a fixed app string. */
export function recordToastError(text: string): void {
  if (Date.now() - lastRecordedAt < TOAST_ECHO_MS || !uiTextKnown(text)) return;
  recordError(`toast: ${text.slice(0, 120)}`);
}

/** Move buffered entries into the open store. Safe to call often; a failed write keeps them buffered. */
export async function flushErrors(): Promise<void> {
  if (!writer || flushing || buffer.length === 0) return;
  flushing = true;
  const batch = [...buffer];
  try {
    if (await writer(batch)) buffer.splice(0, batch.length);
  } catch {
    // Stays buffered; the next flush retries.
  } finally {
    flushing = false;
  }
}

/** The export text: a header (build, device, time), then entries newest first, cut to `maxChars`. */
export function buildErrorExport(entries: ErrorEntry[], now: Date, maxChars = 60_000): { name: string; text: string; shown: number } {
  const date = now.toISOString().slice(0, 10);
  const name = `digitva-errors-${date}.txt`;
  const { device, android } = deviceInfo();
  let text = [`File: ${name}`, `App: DigitVA v${APP_VERSION}`, `Device: ${device}, Android ${android}`, `Exported: ${now.toISOString()}`, `Entries: ${entries.length}`, ""].join("\n");
  let shown = 0;
  for (const entry of entries) {
    const line = `${entry.at} | v${entry.appVersion} | ${entry.route || "-"} | ${entry.what} | ${entry.device}, Android ${entry.android}\n`;
    if (text.length + line.length > maxChars) {
      text += `… ${entries.length - shown} older entries left out to fit the share sheet.\n`;
      break;
    }
    text += line;
    shown += 1;
  }
  return { name, text, shown };
}
