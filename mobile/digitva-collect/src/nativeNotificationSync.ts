/** Foreground notification polling and the coalesced authoritative sync path. */
import { ApiError } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
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

const syncs = new Map<string, Promise<NativeSyncResult>>();

export interface NativeSyncResult {
  sync: SyncResult;
  reference: Awaited<ReturnType<typeof refreshReferenceData>>;
}

export interface NativeSyncCallbacks {
  onSuperseded?(uniqueId: string): void;
  onDraftConflict?(draftId: string): void;
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
  if (existing) return existing;

  let pending!: Promise<NativeSyncResult>;
  pending = (async () => {
    const before = await readNotificationState(userId);
    const sync = await syncInterviewer(
      userId,
      db,
      callbacks.onSuperseded,
      callbacks.onDraftConflict,
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
    if (syncs.get(syncKey) === pending) syncs.delete(syncKey);
  });
  syncs.set(syncKey, pending);
  return pending;
}

/** Poll while active and sync only when nudged or the periodic full-sync window elapsed. */
export async function refreshNativeNotifications(
  userId: string,
  db?: Db,
): Promise<boolean> {
  await pollAccountNotifications(userId);
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
