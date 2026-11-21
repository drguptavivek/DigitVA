import { useEffect, useSyncExternalStore } from "react";
import * as SecureStore from "expo-secure-store";


const KEY = "digitva.icd11-doris-enabled.v1";

export type Icd11DorisPreference = Readonly<{
  ready: boolean;
  answered: boolean;
  enabled: boolean;
}>;

let snapshot: Icd11DorisPreference = Object.freeze({ ready: false, answered: false, enabled: false });
const listeners = new Set<() => void>();
let loadPromise: Promise<void> | undefined;
let writeQueue: Promise<void> = Promise.resolve();

function publish(next: Icd11DorisPreference) {
  snapshot = Object.freeze(next);
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return snapshot;
}

async function load(): Promise<void> {
  if (!loadPromise) {
    loadPromise = (async () => {
      let value: string | null = null;
      try {
        value = await SecureStore.getItemAsync(KEY);
      } catch {
        // An unreadable preference is fail-closed and can be answered again in the first-run gate.
      }
      const valid = value === "enabled" || value === "disabled";
      // Owner 2026-11-21: coding is on by default in Collect and Collect Plus alike, without a first-run question.
      // A stored choice (an earlier "Not now", or Settings) still wins.
      publish({ ready: true, answered: true, enabled: valid ? value === "enabled" : true });
    })();
  }
  await loadPromise;
}

/** Read the device-wide coding preference. Missing, invalid, or unreadable values are enabled (Collect and Collect Plus). */
export async function isIcd11DorisEnabled(): Promise<boolean> {
  await load();
  return snapshot.enabled;
}

/** Persist a device-wide choice before exposing it to subscribers. */
export async function setIcd11DorisEnabled(enabled: boolean): Promise<void> {
  const operation = writeQueue.then(async () => {
    await load();
    await SecureStore.setItemAsync(KEY, enabled ? "enabled" : "disabled");
    publish({ ready: true, answered: true, enabled });
  });
  writeQueue = operation.catch(() => undefined);
  await operation;
}

/** React hook with stable snapshots for settings and the first-launch gate. */
export function useIcd11DorisPreference(): Icd11DorisPreference {
  const value = useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
  useEffect(() => {
    void load();
  }, []);
  return value;
}
