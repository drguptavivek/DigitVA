/** Foreground notification polling and the coalesced authoritative sync path. */
import { ApiError } from "./api";
import { authedRequest, loadAccounts, refreshAccessSummary, SessionRevokedError, SignInRequiredError } from "./auth";
import { isUnlocked } from "./interviewerDb";
import { drainNotificationPages } from "./notificationPoll";
import {
  finishNotificationSync,
  markNotificationSyncPending,
  NOTIFICATION_SYNC_INTERVAL_MS,
  notificationStateGeneration,
  readNotificationState,
  recordNotificationPoll,
  runNotificationPoll,
} from "./notificationState";
import { refreshReferenceData, syncInterviewer, type SyncResult } from "./sync";
import type { Db } from "./drafts";

const syncs = new Map<string, {
  promise: Promise<NativeSyncResult>;
  canCodeNowUniqueIds: string[];
  canCodeNowSubscribers: Set<(uniqueId: string) => void>;
}>();

export interface NativeSyncResult {
  sync: SyncResult;
  reference: Awaited<ReturnType<typeof refreshReferenceData>>;
}

export interface NativeSyncCallbacks {
  onSuperseded?(uniqueId: string): void;
  onDraftConflict?(draftId: string): void;
  onServerKept?(notice: { uniqueId: string; locked: boolean }): void;
  onCanCodeNow?(uniqueId: string): void;
}

function isAuthFailure(error: unknown): boolean {
  return error instanceof SessionRevokedError
    || error instanceof SignInRequiredError
    || (error instanceof ApiError && (error.status === 401 || error.status === 403));
}

/** Poll one account without retaining response rows; authorization failures remain caller-owned. */
export function pollAccountNotifications(userId: string): Promise<void | undefined> {
  return runNotificationPoll(userId, async () => {
    const expectedEpoch = notificationStateGeneration(userId);
    const state = await readNotificationState(userId);
    if (!state || notificationStateGeneration(userId) !== expectedEpoch) return;
    const result = await drainNotificationPages({
      after: state.cursor,
      isAuthorizationError: isAuthFailure,
      request: async (after) =>
        (await authedRequest<unknown>(
          userId,
          `/api/v1/me/notifications?after=${after}`,
          { timeoutMs: 15_000 },
        )).body,
    });
    await recordNotificationPoll(
      userId,
      result.nextCursor,
      result.needsSync,
      expectedEpoch,
    );
  });
}

/** Coalesce manual and notification-driven syncs per account. */
export function runNativeSync(
  userId: string,
  db: Db,
  callbacks: NativeSyncCallbacks = {},
): Promise<NativeSyncResult> {
  const syncEpoch = notificationStateGeneration(userId);
  const syncKey = `${userId}:${syncEpoch}`;
  const existing = syncs.get(syncKey);
  if (existing) {
    if (callbacks.onCanCodeNow) {
      existing.canCodeNowSubscribers.add(callbacks.onCanCodeNow);
      existing.canCodeNowUniqueIds.forEach(callbacks.onCanCodeNow);
    }
    return existing.promise;
  }

  let pending!: Promise<NativeSyncResult>;
  const canCodeNowUniqueIds: string[] = [];
  const canCodeNowSubscribers = new Set<(uniqueId: string) => void>();
  if (callbacks.onCanCodeNow) canCodeNowSubscribers.add(callbacks.onCanCodeNow);
  pending = (async () => {
    await refreshAccessSummary(userId);
    const account = (await loadAccounts()).find(({ user_id }) => user_id === userId);
    if (account?.collection_access !== true) throw new ApiError(403, "no_collection_access");
    const before = await readNotificationState(userId);
    const sync = await syncInterviewer(
      userId,
      db,
      callbacks.onSuperseded,
      callbacks.onDraftConflict,
      callbacks.onServerKept,
      (uniqueId) => {
        if (!canCodeNowUniqueIds.includes(uniqueId)) canCodeNowUniqueIds.push(uniqueId);
        canCodeNowSubscribers.forEach((subscriber) => subscriber(uniqueId));
      },
    );
    const reference = await refreshReferenceData(userId, db, { force: true });
    if (before) {
      await finishNotificationSync(
        userId,
        before.pendingRevision,
        Date.now(),
        syncEpoch,
      );
    }
    return { sync, reference };
  })().finally(() => {
    if (syncs.get(syncKey)?.promise === pending) syncs.delete(syncKey);
    canCodeNowSubscribers.clear();
  });
  syncs.set(syncKey, { promise: pending, canCodeNowUniqueIds, canCodeNowSubscribers });
  return pending;
}

/** Poll while active and sync only when nudged or the periodic full-sync window elapsed. */
export async function refreshNativeNotifications(
  userId: string,
  db?: Db,
): Promise<boolean> {
  await refreshAccessSummary(userId);
  await pollAccountNotifications(userId);
  const account = (await loadAccounts()).find(({ user_id }) => user_id === userId);
  if (account?.collection_access !== true) return false;
  const state = await readNotificationState(userId);
  if (!state) {
    if (!db || !isUnlocked(userId)) return false;
    await runNativeSync(userId, db);
    return true;
  }
  const overdue = state.lastSuccessfulFullSyncAt === null
    || Date.now() - state.lastSuccessfulFullSyncAt >= NOTIFICATION_SYNC_INTERVAL_MS;
  if (overdue && !state.pendingSync) {
    if (!await markNotificationSyncPending(userId)) {
      if (!db || !isUnlocked(userId)) return false;
      await runNativeSync(userId, db);
      return true;
    }
  }
  if (!db || !isUnlocked(userId)) return false;
  const latest = await readNotificationState(userId);
  if (!latest) {
    await runNativeSync(userId, db);
    return true;
  }
  if (!latest.pendingSync) return false;
  await runNativeSync(userId, db);
  return true;
}
