import { useRouter } from "expo-router";
import { useEffect } from "react";

type Router = ReturnType<typeof useRouter>;
type Href = Parameters<Router["replace"]>[0];

/**
 * Back to the accounts list with a one-screen stack. Every screen lives in one root Stack, so
 * `replace("/")` alone swaps only the top route and leaves what was under it mounted: each
 * lock / switch / sign-out would add a screen. Pop to the first route (the accounts list), then
 * replace it so it re-reads state. `href` replaces the accounts list instead (re-enrolment).
 */
export function goHome(router: Router, href: Href = "/"): void {
  if (router.canDismiss()) router.dismissAll();
  router.replace(href);
}

/** `<Redirect href="/" />` that also clears the stack below, so Back cannot return to the guarded screen. */
export function RedirectHome() {
  const router = useRouter();
  useEffect(() => {
    goHome(router);
  }, [router]);
  return null;
}
