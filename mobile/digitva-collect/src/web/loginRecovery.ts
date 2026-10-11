export type AccountActionCode = "terms_required";

function currentAppRoute(currentHref?: string): string {
  const fallback = "/app/";
  try {
    const base = currentHref ?? (typeof window === "undefined" ? "https://digitva.invalid/app/" : window.location.href);
    const current = new URL(base, "https://digitva.invalid/app/");
    if (current.pathname !== "/app" && !current.pathname.startsWith("/app/")) return fallback;
    return `${current.pathname}${current.search}`;
  } catch {
    return fallback;
  }
}

/**
 * Add the current Expo browser route to a normal authentication login link.
 * Account setup uses fixed internal destinations. Unsafe or cross-origin
 * sign-in links fall back to the app root.
 */
export function loginRecoveryUrl(
  loginUrl: string | undefined,
  actionCode?: AccountActionCode,
  currentHref?: string
): string {
  if (actionCode === "terms_required") return "/profile/force-password-change";
  if (!loginUrl) return "/";
  try {
    const base = currentHref ?? (typeof window === "undefined" ? "https://digitva.invalid/app/" : window.location.href);
    const current = new URL(base, "https://digitva.invalid/app/");
    const target = new URL(loginUrl, current);
    if (!/^https?:$/.test(target.protocol) || target.origin !== current.origin || target.pathname !== "/vaauth/valogin") return "/";
    target.searchParams.set("next", currentAppRoute(current.href));
    if (loginUrl.startsWith("/") && !loginUrl.startsWith("//")) {
      return `${target.pathname}${target.search}${target.hash}`;
    }
    return target.toString();
  } catch {
    return "/";
  }
}
