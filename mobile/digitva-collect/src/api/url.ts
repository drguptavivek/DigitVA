/** Same-origin check for server-provided action links; pure, shared by the transport and the intake calls. */
export function safeActionUrl(value: unknown): string | undefined {
  if (typeof value !== "string" || !value) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  if (typeof window === "undefined") return undefined;
  try {
    const target = new URL(value, window.location.href);
    return target.origin === window.location.origin
      ? target.toString()
      : undefined;
  } catch {
    return undefined;
  }
}
