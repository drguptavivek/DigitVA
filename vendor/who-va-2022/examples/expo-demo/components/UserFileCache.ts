import * as FileSystem from "expo-file-system/legacy";

const USER_CACHE_DIRS = ["who-va-attachments", "who-va-exports"];

export async function clearDownloadedUserCaches(): Promise<void> {
  if (!FileSystem.documentDirectory) return;
  await Promise.all(
    USER_CACHE_DIRS.map((directory) =>
      FileSystem.deleteAsync(`${FileSystem.documentDirectory}${directory}/`, { idempotent: true })
    )
  );
}
