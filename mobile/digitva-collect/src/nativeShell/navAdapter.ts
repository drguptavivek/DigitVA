/**
 * Native adapter over src/web/navTabs.ts: the same role-to-destination rules as the browser menu, narrowed to
 * what the app does (docs/policy/field-data-collection.md: online coding and review are Code and Review tabs), plus the pure rules for when the phone chrome shows.
 */
import type { ClientBootstrap } from "../client/api";
import type { Account } from "../auth";
import type { StringKey } from "../i18n";
import { canUseOnlineCoding } from "../codingCapabilities";
import { navEntries } from "../web/navTabs";

/** Pre-login and device screens: no header, no tabs. */
export const NATIVE_HEADERLESS_ROUTES = ["/sign-in", "/enrol", "/unlock", "/pin-setup"];
/** Full-height form screens: their own 48dp bar replaces the header, and no tabs. */
export const NATIVE_IMMERSIVE_ROUTES = ["/form", "/revision"];

export interface NativeTab {
  key: "home" | "interviews" | "register" | "code" | "review" | "sync";
  labelKey: StringKey;
  /** Absent for Sync, which opens a sheet. */
  route?: string;
  params?: Record<string, string>;
}

type AccessInput = Pick<Account, "collection_access" | "registration_access" | "registered_deaths_access" | "standalone" | "coding_access" | "reviewing_access" | "needs_sign_in" | "access_blocked">;

/** The account's access summary dressed as the browser bootstrap navEntries reads. */
function asBootstrap(account: AccessInput): Pick<ClientBootstrap, "access" | "capabilities"> {
  return {
    access: { roles: [] },
    capabilities: {
      intake: account.collection_access === true,
      registerDeath: account.registration_access === true,
      registeredDeaths: account.registered_deaths_access === true,
    },
  } as unknown as Pick<ClientBootstrap, "access" | "capabilities">;
}

/** Standalone stays on local Home and Interviews; enrolled accounts get access-based tabs and Sync. */
export function nativeTabs(account: AccessInput | undefined): NativeTab[] {
  if (account?.standalone) {
    return [
      { key: "home", labelKey: "home", route: "/standalone" },
      { key: "interviews", labelKey: "tabInterviews", route: "/standalone", params: { view: "interviews" } },
    ];
  }
  const keys = new Set(account ? navEntries(asBootstrap(account)).primary.map((entry) => entry.key) : []);
  const tabs: NativeTab[] = [{ key: "home", labelKey: "home", route: "/worklist" }];
  if (keys.has("/collection")) tabs.push({ key: "interviews", labelKey: "tabInterviews", route: "/worklist", params: { view: "interviews" } });
  // A death reporter's own list is on Home; the Register death tab is for those who may register.
  if (keys.has("/death-registration") && account?.registration_access === true) tabs.push({ key: "register", labelKey: "tabRegister", route: "/register" });
  // Online coding for coders in both variants; a pending sign-in or blocked account cannot open it.
  if (account && canUseOnlineCoding(account) && !account.needs_sign_in && !account.access_blocked) tabs.push({ key: "code", labelKey: "tabCode", route: "/coding" });
  // Online review for reviewers, same gate as Code.
  if (account?.reviewing_access === true && !account.needs_sign_in && !account.access_blocked) tabs.push({ key: "review", labelKey: "tabReview", route: "/reviewing" });
  tabs.push({ key: "sync", labelKey: "tabSync" });
  return tabs;
}

/** The tab a screen belongs to. */
export function activeNativeTab(pathname: string, params: { view?: string | string[]; mode?: string | string[] } = {}): NativeTab["key"] | undefined {
  const view = Array.isArray(params.view) ? params.view[0] : params.view;
  const mode = Array.isArray(params.mode) ? params.mode[0] : params.mode;
  if (pathname === "/standalone") return view === "interviews" ? "interviews" : "home";
  if (pathname === "/worklist") return view === "interviews" ? "interviews" : "home";
  if (pathname === "/case") return "interviews";
  if (pathname === "/register") return "register";
  if (pathname === "/coding" || (pathname === "/workspace" && mode === "coding")) return "code";
  if (pathname === "/reviewing" || (pathname === "/workspace" && mode === "reviewing")) return "review";
  return undefined;
}

/**
 * How a tab tap moves the root Stack without remounting a screen that is already in it (a remount draws the
 * screen blank and reloads its data, which flashed on every tab tap):
 * - `dismissTo`: Home and Interviews always (they share the account's home route), and any tab whose route is
 *   already in the stack. The stack pops back to that screen and replaces its params, keeping it mounted; a
 *   route that is not in the stack replaces the current screen, as tab taps always did.
 * - `push`: a tab first opened from a tab root (Register from Home), so Back and Home return to the screen below.
 * - `replace`: a tab first opened from a pushed screen (a case), so it does not stack on top of the case.
 * `stackRoutes` are the root Stack's route names, bottom first (`"worklist"`, `"register"`, ...).
 */
export function tabMove(tab: NativeTab, homeRoute: string, stackRoutes: string[], atTabRoot: boolean): "dismissTo" | "push" | "replace" {
  if (tab.route === homeRoute || stackRoutes.includes(tab.route!.replace(/^\//, ""))) return "dismissTo";
  return atTabRoot ? "push" : "replace";
}

/**
 * Whether the screen is a tab root (the accounts list or a bottom-tab destination), where the header shows the
 * emblem; any other screen shows a back arrow. `/register` is a root only for accounts that have its tab.
 */
export function isNativeTabRoot(pathname: string, account: AccessInput | undefined): boolean {
  return pathname === "/" || nativeTabs(account).some((tab) => tab.route === pathname);
}

/**
 * A pushed screen with the header showing: the bar draws a back arrow and the screen's title, and Screen drops its
 * on-page title. Tab roots, pre-login and immersive screens keep the emblem or have no header.
 */
export function showNativeBackTitle(pathname: string, account: AccessInput | undefined): boolean {
  return showNativeHeader(pathname) && !isNativeTabRoot(pathname, account);
}

export interface ChromeInput {
  pathname: string;
  userId: string | undefined;
  /** The account is known and its store is open. */
  unlocked: boolean;
  keyboardOpen: boolean;
}

/** The sign-in, enrol, unlock and PIN screens: a minimal header (emblem, title, app language), no back arrow and no tabs. */
export function isPreLoginRoute(pathname: string): boolean {
  return NATIVE_HEADERLESS_ROUTES.includes(pathname);
}

/** Header: everywhere except forms and the pre-login/device screens. */
export function showNativeHeader(pathname: string): boolean {
  return !NATIVE_HEADERLESS_ROUTES.includes(pathname) && !NATIVE_IMMERSIVE_ROUTES.includes(pathname);
}

/** Tabs: a signed-in, unlocked interviewer on a normal screen with the keyboard closed. The accounts list ("/") has none. */
export function showNativeTabs({ pathname, userId, unlocked, keyboardOpen }: ChromeInput): boolean {
  return Boolean(userId) && unlocked && !keyboardOpen && pathname !== "/" && showNativeHeader(pathname);
}
