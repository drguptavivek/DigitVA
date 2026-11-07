/** Access answer as stable JSON: the server stamps `server_time` on every call, which is not an access change; `project_today` stays so a daily change reconciles. */
export function stableAccessJson(value: unknown): string {
  return JSON.stringify(value, (key, entry) => key === "server_time" ? undefined : entry);
}
