/** Module-scope Android WorkManager task; it only polls and writes sync metadata. */
import * as BackgroundTask from "expo-background-task";
import * as TaskManager from "expo-task-manager";
import { Platform } from "react-native";

import { authedRequest, loadAccounts, SessionRevokedError, SignInRequiredError } from "./auth";
import { drainNotificationPages } from "./notificationPoll";
import {
  notificationStateGeneration,
  readNotificationState,
  recordNotificationPoll,
  runNotificationPoll,
} from "./notificationState";

export const NATIVE_NOTIFICATION_TASK = "digitva-notification-poll";
let registration = Promise.resolve();

export async function runNativeNotificationTask(): Promise<void> {
  const accounts = await loadAccounts();
  for (const account of accounts) {
    if (account.needs_sign_in || account.terms_required || account.access_blocked) continue;
    await runNotificationPoll(account.user_id, async () => {
      const expectedEpoch = notificationStateGeneration(account.user_id);
      const state = await readNotificationState(account.user_id);
      if (!state || notificationStateGeneration(account.user_id) !== expectedEpoch) return;
      const result = await drainNotificationPages({
        after: state.cursor,
        isAuthorizationError: (error) =>
          error instanceof SessionRevokedError
          || error instanceof SignInRequiredError
          || (typeof error === "object" && error !== null
            && "status" in error && (error.status === 401 || error.status === 403)),
        request: async (after) =>
          (await authedRequest<unknown>(
            account.user_id,
            `/api/v1/me/notifications?after=${after}`,
            { timeoutMs: 15_000 },
          )).body,
      });
      await recordNotificationPoll(
        account.user_id,
        result.nextCursor,
        result.needsSync,
        expectedEpoch,
      );
    });
  }
}

if (Platform.OS === "android") {
  TaskManager.defineTask(NATIVE_NOTIFICATION_TASK, async () => {
    try {
      await runNativeNotificationTask();
      return BackgroundTask.BackgroundTaskResult.Success;
    } catch {
      return BackgroundTask.BackgroundTaskResult.Failed;
    }
  });
}

/** Register one Android worker for all eligible signed-in accounts. */
export async function syncNotificationTaskRegistration(
  eligible: boolean,
): Promise<void> {
  if (Platform.OS !== "android") return;
  const next = registration.catch(() => undefined).then(async () => {
    const tasks = await TaskManager.getRegisteredTasksAsync();
    const registered = tasks.some(({ taskName }) => taskName === NATIVE_NOTIFICATION_TASK);
    if (eligible && !registered) {
      await BackgroundTask.registerTaskAsync(NATIVE_NOTIFICATION_TASK, {
        minimumInterval: 15,
      });
    } else if (!eligible && registered) {
      await BackgroundTask.unregisterTaskAsync(NATIVE_NOTIFICATION_TASK);
    }
  });
  registration = next;
  await next;
}
