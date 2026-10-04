/** Background tasks are native-only; web polls in AppState.web without a
 * WorkManager task.
 */
export const NATIVE_NOTIFICATION_TASK = "digitva-notification-poll";

export async function runNativeNotificationTask(): Promise<void> {}

export async function syncNotificationTaskRegistration(
  _eligible: boolean,
): Promise<void> {
  // Web uses the foreground notification flow from AppState.web.
}
