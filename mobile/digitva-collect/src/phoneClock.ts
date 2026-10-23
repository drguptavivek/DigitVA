/**
 * Phone clock check (docs/policy/field-data-collection.md, "Phone clock"). The offset is phone minus server,
 * measured from the `Date` header of server responses and kept on the device (not per user) so it survives
 * restarts and applies offline. Under 5 minutes is ignored; 5 minutes to 4 hours warns; more than 4 hours
 * blocks data entry. A phone that never measured an offset is not judged.
 */
import { useSyncExternalStore } from "react";

export const WARN_SECONDS = 5 * 60;
export const BLOCK_SECONDS = 4 * 3600;
const KEY = "phone_clock";
/** Loaded on use: api.ts imports this module, and the store has no native module in every context (tests, web). */
const secureStore = () => require("expo-secure-store") as typeof import("expo-secure-store");
/** A measurement within this of the stored offset is averaged in; a bigger jump (the user fixed the clock) replaces it. */
const JUMP_SECONDS = 60;

export interface PhoneClock {
  offsetSeconds: number;
  measuredAt: number;
}
export type ClockLevel = "ok" | "warn" | "block";

let current: PhoneClock | undefined;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());

/** Server time in ms from an HTTP `Date` header, or undefined when absent or unparsable. */
export function parseServerDate(header: string | null | undefined): number | undefined {
  if (!header) return undefined;
  const ms = Date.parse(header);
  return Number.isNaN(ms) ? undefined : ms;
}

export function clockLevel(offsetSeconds: number | undefined): ClockLevel {
  const size = Math.abs(offsetSeconds ?? 0);
  return size > BLOCK_SECONDS ? "block" : size >= WARN_SECONDS ? "warn" : "ok";
}

/** Fold one measurement into the stored offset. */
export function smoothOffset(previous: number | undefined, measured: number): number {
  if (previous === undefined || Math.abs(measured - previous) > JUMP_SECONDS) return measured;
  return Math.round((previous + measured) / 2);
}

export function getPhoneClock(): PhoneClock | undefined {
  return current;
}

/** The offset to send in device envelopes: whole seconds, or undefined when never measured. */
export function clockOffsetSeconds(): number | undefined {
  return current?.offsetSeconds;
}

/** `draft.clockOffsetSeconds` for a device envelope; empty when never measured. */
export function clockOffsetField(): { clockOffsetSeconds?: number } {
  return current ? { clockOffsetSeconds: current.offsetSeconds } : {};
}

/** Now, corrected by the last known offset (the server's time as best the phone knows it). */
export function correctedNow(): Date {
  return new Date(Date.now() - (current?.offsetSeconds ?? 0) * 1000);
}

function persist(): void {
  if (!current) return;
  try {
    void secureStore().setItemAsync(KEY, JSON.stringify(current)).catch(() => undefined);
  } catch {
    // No secure store here: the offset lives for this run only.
  }
}

/** Record the `Date` header of a server response. `phoneNow` is injectable for tests. */
export function recordServerDate(header: string | null | undefined, phoneNow = Date.now()): void {
  const serverMs = parseServerDate(header);
  if (serverMs === undefined) return;
  const measured = Math.round((phoneNow - serverMs) / 1000);
  current = { offsetSeconds: smoothOffset(current?.offsetSeconds, measured), measuredAt: phoneNow };
  persist();
  emit();
}

/** Load the stored offset once at start-up; never overwrites a measurement already taken. */
export async function loadPhoneClock(): Promise<void> {
  if (current) return;
  try {
    const raw = await secureStore().getItemAsync(KEY);
    const parsed = raw ? JSON.parse(raw) : undefined;
    if (!current && Number.isInteger(parsed?.offsetSeconds) && Number.isFinite(parsed?.measuredAt)) {
      current = { offsetSeconds: parsed.offsetSeconds, measuredAt: parsed.measuredAt };
      emit();
    }
  } catch {
    // An unreadable value is the same as never measured.
  }
}

/** Re-check against the server with one light public request; true when a Date header was read. */
export async function recheckPhoneClock(server: string): Promise<boolean> {
  const before = current?.measuredAt;
  try {
    const response = await fetch(`${server}/api/v1/app/android/latest`, { cache: "no-store" });
    recordServerDate(response.headers.get("Date"));
  } catch {
    // Offline: the stored offset stays and so does any block.
  }
  return current?.measuredAt !== before;
}

/** Test hook. */
export function resetPhoneClock(): void {
  current = undefined;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => void listeners.delete(listener);
}

export function usePhoneClock(): { clock: PhoneClock | undefined; level: ClockLevel } {
  const clock = useSyncExternalStore(subscribe, getPhoneClock, getPhoneClock);
  return { clock, level: clockLevel(clock?.offsetSeconds) };
}
