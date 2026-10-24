/** Pure navigation rules of the browser app: the items a user sees, which one is current, when the phone bottom bar shows. */
import type { ClientBootstrap } from "../client/api";
import type { StringKey } from "../i18n";
import { TRAINING_ROUTES, trainingAreas } from "../training";
import { dataAccess, roleScreens, statisticsAllowed } from "./roleHome";

/** Pre-login and device screens: nobody is signed in to see navigation there. */
export const HEADERLESS_ROUTES = ["/sign-in", "/enrol", "/unlock", "/pin-setup", "/register"];

export type NavParams = { vaSid?: string | string[]; mode?: string | string[]; training?: string | string[] };

/**
 * One navigation destination. `key` is the in-app route when there is one (so it compares with `activeTab`).
 * Exactly one of `route` (in-app, optional `params`), `serverPath` (full-page Flask page, remembered as a visit)
 * or `href` (opens in a new tab) is set.
 */
export type NavEntry = {
  key: string;
  labelKey: StringKey;
  route?: string;
  params?: Record<string, string>;
  serverPath?: string;
  href?: string;
  /** Sub-items shown under this one in the left menu (Training); the phone bottom bar shows the parent only. */
  children?: NavEntry[];
};

type NavBootstrap = Pick<ClientBootstrap, "access" | "capabilities">;

const TRAINING_LABELS: Record<keyof typeof TRAINING_ROUTES, StringKey> = {
  interview: "trainingInterview",
  coding: "trainingCoding",
  review: "trainingReview",
};

/** The public website (Flask va_main.va_index), the same page the account menu's "Open web version" opens. */
export const WEBSITE_HREF = "/vaindex";

/**
 * The menu of the left sidebar (wide) and the bottom bar (phone), identical in both: `primary` in the owner's
 * order, then everything else under More. Visibility reuses roleScreens/dataAccess; Admin console copies the home
 * screen's rule (WorkspaceScreen). Showing an item grants nothing: every route checks access on the server.
 * Sign out is not an entry; each menu appends it to More.
 */
export function navEntries(bootstrap: NavBootstrap): { primary: NavEntry[]; more: NavEntry[] } {
  const screens = roleScreens(bootstrap);
  const roles = bootstrap.access?.roles ?? [];
  const caps = bootstrap.capabilities;
  const primary: NavEntry[] = [{ key: "/", labelKey: "home", route: "/" }];
  if (screens.includes("/death-registration")) {
    // The deaths list for anyone who interviews or reports deaths (docs/policy/case-list-views.md); otherwise the form.
    // A supervisor with no deaths of their own lands on the supervision preset.
    const params: Record<string, string> | undefined = caps?.registeredDeaths || caps?.intake ? { view: "mine" } : caps?.supervision ? { view: "mine", preset: "supervision" } : undefined;
    primary.push({ key: "/death-registration", labelKey: "navDeaths", route: "/death-registration", ...(params ? { params } : {}) });
  }
  if (screens.includes("/collection")) primary.push({ key: "/collection", labelKey: "navVaInterview", route: "/collection" });
  if (screens.includes("/coding")) primary.push({ key: "/coding", labelKey: "navVaCode", route: "/coding" });
  if (screens.includes("/reviewing")) primary.push({ key: "/reviewing", labelKey: "navVaReview", route: "/reviewing" });
  // Any active grant (policy area-dashboard.md); the API still scopes every number to the user's area.
  if (statisticsAllowed(bootstrap)) primary.push({ key: "/statistics", labelKey: "navStatistics", route: "/statistics" });
  // Only an active participation in a training session shows it; its sub-items follow the training roles held.
  const areas = trainingAreas(bootstrap.access);
  if (areas.length > 0) {
    primary.push({
      key: "/training", labelKey: "navTraining", route: "/training",
      children: areas.map((area) => ({ key: TRAINING_ROUTES[area], labelKey: TRAINING_LABELS[area], route: TRAINING_ROUTES[area] })),
    });
  }

  const more: NavEntry[] = [{ key: "/organization", labelKey: "navOrg", route: "/organization" }];
  // The Users page's server gate (GET /api/v1/users): admin, project PI or data manager (the In-charge included).
  if (bootstrap.access?.is_admin || roles.some((role) => role === "admin" || role === "project_pi" || role === "data_manager")) {
    more.push({ key: "/users", labelKey: "navUsers", route: "/users" });
  }
  more.push(
    { key: "/settings", labelKey: "navSettings", route: "/settings" },
    { key: "website", labelKey: "navWebsite", href: WEBSITE_HREF },
  );
  if (dataAccess(bootstrap).allowed) more.push({ key: "/data", labelKey: "navData", route: "/data" });
  if (screens.includes("/mentoring")) more.push({ key: "/mentoring", labelKey: "navMentoring", route: "/mentoring" });
  if (bootstrap.access?.is_admin || roles.includes("admin")) more.push({ key: "/admin/", labelKey: "homeAdminConsole", serverPath: "/admin/" });
  return { primary, more };
}

const first = (value: string | string[] | undefined) => (Array.isArray(value) ? value[0] : value)?.trim();

/** The item route a path belongs to, or undefined (a view-only workspace, unknown routes). /workspace belongs to Coding or Review by its `mode`. */
export function activeTab(pathname: string, params: NavParams = {}): string | undefined {
  if (pathname === "/") return "/";
  if (pathname === "/workspace") {
    const mode = first(params.mode);
    // A case opened from the Training menu keeps that item highlighted.
    if (first(params.training) === "1") return mode === "coding" ? TRAINING_ROUTES.coding : mode === "reviewing" ? TRAINING_ROUTES.review : undefined;
    return mode === "coding" ? "/coding" : mode === "reviewing" ? "/reviewing" : undefined;
  }
  // Training: the overview, or one of its sub-items.
  if (pathname === "/training" || pathname.startsWith("/training/")) {
    return Object.values(TRAINING_ROUTES).includes(pathname) ? pathname : "/training";
  }
  // The interview form and a case's details are reached from VA Interview.
  if (["/worklist", "/interview", "/case", "/form"].includes(pathname)) return "/collection";
  return ["/coding", "/reviewing", "/collection", "/death-registration", "/mentoring", "/statistics", "/data", "/organization", "/users", "/settings"]
    .find((route) => pathname === route || pathname.startsWith(`${route}/`));
}

/** The phone bottom bar: every signed-in screen except the case workspace (/workspace with a vaSid, coding/review focus) and the pre-login routes. */
export function showBottomTabs(pathname: string, params: NavParams = {}): boolean {
  if (HEADERLESS_ROUTES.includes(pathname)) return false;
  if (pathname === "/workspace" && first(params.vaSid)) return false;
  return true;
}
