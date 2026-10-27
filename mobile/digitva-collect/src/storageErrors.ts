/** True when SQLite refused a write because the phone's storage is full (SQLITE_FULL, extended codes included). */
export function isStorageFull(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const { message, code } = error as { message?: unknown; code?: unknown };
  const text = `${typeof message === "string" ? message : ""} ${typeof code === "string" ? code : ""}`;
  return /SQLITE_FULL|database or disk is full|disk is full|No space left/i.test(text);
}
