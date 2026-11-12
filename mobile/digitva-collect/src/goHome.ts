import type { useRouter } from "expo-router";

/**
 * Back to the accounts list with a one-screen stack. Every screen lives in one root Stack, so
 * `replace("/")` alone swaps only the top route and leaves what was under it mounted: each
 * lock / switch / sign-out would add a screen. Pop to the first route (the accounts list), then
 * replace it so it re-reads state.
 */
export function goHome(router: ReturnType<typeof useRouter>): void {
  if (router.canDismiss()) router.dismissAll();
  router.replace("/");
}
