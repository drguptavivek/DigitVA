/**
 * Per-account notification cursor and sync hints. This contains no notification
 * rows or interview data and is stored separately from the encrypted database.
 */
import * as SecureStore from "expo-secure-store";
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";
import { createNotificationPollGate } from "./notificationPoll";

const PREFIX = "notification_state.v1.";
const OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export interface NotificationState {
  cursor: number;
  pendingSync: boolean;
  pendingRevision: number;
  lastSuccessfulFullSyncAt: number | null;
}

export const NOTIFICATION_SYNC_INTERVAL_MS = 15 * 60_000;

const defaults = (): NotificationState => ({
  cursor: 0,
  pendingSync: false,
  pendingRevision: 0,
  lastSuccessfulFullSyncAt: null,
});

const epochs = new Map<string, number>();
const writes = new Map<string, Promise<void>>();
const disabled = new Set<string>();
const pollGates = new Map<string, ReturnType<typeof createNotificationPollGate>>();

/** Share one 30-second poll floor and in-flight request per account across app states. */
export function runNotificationPoll<T>(userId: string, task: () => Promise<T>): Promise<T | undefined> {
  let gate = pollGates.get(userId);
  if (!gate) {
    gate = createNotificationPollGate();
    pollGates.set(userId, gate);
  }
  return gate.run(task);
}

async function keyFor(userId: string): Promise<string> {
  const hash = await digestStringAsync(CryptoDigestAlgorithm.SHA256, userId);
  return `${PREFIX}${hash}`;
}

function parseState(raw: string | null): NotificationState | undefined {
  if (raw === null) return defaults();
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null || Array.isArray(value)) return undefined;
    const state = value as Record<string, unknown>;
    if (!Number.isSafeInteger(state.cursor) || (state.cursor as number) < 0
      || typeof state.pendingSync !== "boolean"
      || !Number.isSafeInteger(state.pendingRevision) || (state.pendingRevision as number) < 0
      || !(state.lastSuccessfulFullSyncAt === null
        || (Number.isSafeInteger(state.lastSuccessfulFullSyncAt)
          && (state.lastSuccessfulFullSyncAt as number) >= 0))) {
      return undefined;
    }
    return {
      cursor: state.cursor as number,
      pendingSync: state.pendingSync,
      pendingRevision: state.pendingRevision as number,
      lastSuccessfulFullSyncAt: state.lastSuccessfulFullSyncAt as number | null,
    };
  } catch {
    return undefined;
  }
}

function serialize<T>(userId: string, operation: () => Promise<T>): Promise<T> {
  const previous = writes.get(userId) ?? Promise.resolve();
  const current = previous.catch(() => undefined).then(operation);
  const tail = current.then(() => undefined, () => undefined);
  writes.set(userId, tail);
  void tail.then(() => {
    if (writes.get(userId) === tail) writes.delete(userId);
  });
  return current;
}

/** Capture before network work so a result started before a wipe cannot restore metadata. */
export function notificationStateGeneration(userId: string): number {
  return epochs.get(userId) ?? 0;
}

/** Read only nonsensitive notification metadata; undefined means SecureStore is unavailable or invalid. */
export async function readNotificationState(userId: string): Promise<NotificationState | undefined> {
  const epoch = epochs.get(userId) ?? 0;
  return serialize(userId, async () => {
    if (disabled.has(userId) || (epochs.get(userId) ?? 0) !== epoch) return undefined;
    try {
      const raw = await SecureStore.getItemAsync(await keyFor(userId), OPTIONS);
      if (disabled.has(userId) || (epochs.get(userId) ?? 0) !== epoch) return undefined;
      const state = parseState(raw);
      if (state) return state;
      const recovered: NotificationState = {
        ...defaults(),
        pendingSync: true,
        pendingRevision: 1,
      };
      await SecureStore.setItemAsync(await keyFor(userId), JSON.stringify(recovered), OPTIONS);
      if (disabled.has(userId) || (epochs.get(userId) ?? 0) !== epoch) return undefined;
      return recovered;
    } catch {
      return undefined;
    }
  });
}

/** Persist a validated cursor only after preserving any required normal sync. */
export async function recordNotificationPoll(
  userId: string,
  cursor: number,
  needsSync: boolean,
  expectedEpoch = notificationStateGeneration(userId),
): Promise<NotificationState | undefined> {
  if (!Number.isSafeInteger(cursor) || cursor < 0) return undefined;
  return serialize(userId, async () => {
    if (disabled.has(userId) || notificationStateGeneration(userId) !== expectedEpoch) return undefined;
    try {
      const key = await keyFor(userId);
      const current = parseState(await SecureStore.getItemAsync(key, OPTIONS));
      if (!current || disabled.has(userId)
        || notificationStateGeneration(userId) !== expectedEpoch) return undefined;
      let next = current;
      if (needsSync) {
        next = {
          ...current,
          pendingSync: true,
          pendingRevision: current.pendingRevision + 1,
        };
        await SecureStore.setItemAsync(key, JSON.stringify(next), OPTIONS);
        if (disabled.has(userId) || notificationStateGeneration(userId) !== expectedEpoch) return undefined;
      }
      next = { ...next, cursor };
      await SecureStore.setItemAsync(key, JSON.stringify(next), OPTIONS);
      return !disabled.has(userId)
        && notificationStateGeneration(userId) === expectedEpoch ? next : undefined;
    } catch {
      return undefined;
    }
  });
}

/** Mark an uncertain or overdue state for authoritative sync without advancing its cursor. */
export async function markNotificationSyncPending(userId: string): Promise<NotificationState | undefined> {
  const epoch = notificationStateGeneration(userId);
  const current = await readNotificationState(userId);
  if (!current) return undefined;
  return recordNotificationPoll(userId, current.cursor, true, epoch);
}

/** Record a successful full sync and retain nudges received while it was running. */
export async function finishNotificationSync(
  userId: string,
  pendingRevision: number,
  completedAt: number,
  expectedEpoch = notificationStateGeneration(userId),
): Promise<NotificationState | undefined> {
  return serialize(userId, async () => {
    if (disabled.has(userId) || notificationStateGeneration(userId) !== expectedEpoch) return undefined;
    try {
      const key = await keyFor(userId);
      const current = parseState(await SecureStore.getItemAsync(key, OPTIONS));
      if (!current || disabled.has(userId)
        || notificationStateGeneration(userId) !== expectedEpoch) return undefined;
      const next = {
        ...current,
        pendingSync: current.pendingRevision !== pendingRevision,
        lastSuccessfulFullSyncAt: completedAt,
      };
      await SecureStore.setItemAsync(key, JSON.stringify(next), OPTIONS);
      return !disabled.has(userId)
        && notificationStateGeneration(userId) === expectedEpoch ? next : undefined;
    } catch {
      return undefined;
    }
  });
}

/** Invalidate late writes immediately, then delete this account's metadata. */
export function clearNotificationState(userId: string): Promise<void> {
  epochs.set(userId, (epochs.get(userId) ?? 0) + 1);
  disabled.add(userId);
  return serialize(userId, async () => {
    try {
      await SecureStore.deleteItemAsync(await keyFor(userId), OPTIONS);
    } catch {
      // SecureStore can be unavailable before device unlock; stale operations are epoch-guarded.
    }
  });
}

/** Clear old cursor state after a successful sign-in and allow fresh polls. */
export function resetNotificationState(userId: string): Promise<void> {
  epochs.set(userId, (epochs.get(userId) ?? 0) + 1);
  disabled.delete(userId);
  return serialize(userId, async () => {
    try {
      await SecureStore.deleteItemAsync(await keyFor(userId), OPTIONS);
    } catch {
      // A sign-in requires accessible SecureStore for tokens; keep metadata best-effort.
    }
  });
}
