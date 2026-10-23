/**
 * Native adapter over src/web/navTabs.ts: the same role-to-destination rules as the browser menu, narrowed to
 * what the Android app does (docs/policy/field-data-collection.md: coding and review are web-only, so they never
 * appear), plus the pure rules for when the phone chrome shows.
 */
import type { ClientBootstrap } from "../client/api";
import type { Account } from "../auth";
import type { StringKey } from "../i18n";
import { navEntries } from "../web/navTabs";

/** Pre-login and device screens: no header, no tabs. */
export const NATIVE_HEADERLESS_ROUTES = ["/sign-in", "/enrol", "/unlock", "/pin-setup"];
/** Full-height form screens: their own 48dp bar replaces the header, and no tabs. */
export const NATIVE_IMMERSIVE_ROUTES = ["/form", "/revision"];

export interface NativeTab {
  key: "home" | "interviews" | "register" | "sync";
  labelKey: StringKey;
  /** Absent for Sync, which opens a sheet. */
  route?: string;
  params?: Record<string, string>;
}

type AccessInput = Pick<Account, "collection_access" | "registration_access" | "registered_deaths_access">;

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

/** Home, then Interviews and Register death by access, then Sync. Never a coding or review entry. */
export function nativeTabs(account: AccessInput | undefined): NativeTab[] {
  const keys = new Set(account ? navEntries(asBootstrap(account)).primary.map((entry) => entry.key) : []);
  const tabs: NativeTab[] = [{ key: "home", labelKey: "home", route: "/worklist" }];
  if (keys.has("/collection")) tabs.push({ key: "interviews", labelKey: "tabInterviews", route: "/worklist", params: { view: "interviews" } });
  // A death reporter's own list is on Home; the Register death tab is for those who may register.
  if (keys.has("/death-registration") && account?.registration_access === true) tabs.push({ key: "register", labelKey: "registerDeath", route: "/register" });
  tabs.push({ key: "sync", labelKey: "tabSync" });
  return tabs;
}

/** The tab a screen belongs to. */
export function activeNativeTab(pathname: string, params: { view?: string | string[] } = {}): NativeTab["key"] | undefined {
  const view = Array.isArray(params.view) ? params.view[0] : params.view;
  if (pathname === "/worklist") return view === "interviews" ? "interviews" : "home";
  if (pathname === "/case") return "interviews";
  if (pathname === "/register") return "register";
  return undefined;
}

export interface ChromeInput {
  pathname: string;
  userId: string | undefined;
  /** The account is known and its store is open. */
  unlocked: boolean;
  keyboardOpen: boolean;
}

/** Header: everywhere except forms and the pre-login/device screens. */
export function showNativeHeader(pathname: string): boolean {
  return !NATIVE_HEADERLESS_ROUTES.includes(pathname) && !NATIVE_IMMERSIVE_ROUTES.includes(pathname);
}

/** Tabs: a signed-in, unlocked interviewer on a normal screen with the keyboard closed. The accounts list ("/") has none. */
export function showNativeTabs({ pathname, userId, unlocked, keyboardOpen }: ChromeInput): boolean {
  return Boolean(userId) && unlocked && !keyboardOpen && pathname !== "/" && showNativeHeader(pathname);
}
