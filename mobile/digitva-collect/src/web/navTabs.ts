/** Pure navigation rules of the browser app: the items a user sees, which one is current, when the phone bottom bar shows. */
import type { ClientBootstrap } from "../client/api";
import type { StringKey } from "../i18n";
import { TRAINING_REPORTING_ROUTE, TRAINING_ROUTES, trainingAreas } from "../training";
import { roleScreens, statisticsAllowed } from "./roleHome";

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

/**
 * The menu of the left sidebar (wide) and the bottom bar (phone), identical in both: `primary` in the owner's
 * order, then everything else under More. Visibility reuses roleScreens; Admin console copies the home
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
  more.push({ key: "/settings", labelKey: "navSettings", route: "/settings" });
  if (screens.includes("/mentoring")) more.push({ key: "/mentoring", labelKey: "navMentoring", route: "/mentoring" });
  // Mentor view: mentoring staff, data managers (In-charge included) and admin; the server re-derives the districts.
  if (screens.includes("/mentoring") || bootstrap.access?.is_admin || roles.includes("admin") || roles.includes("data_manager")) {
    more.push({ key: "/mentor-view", labelKey: "navMentorView", route: "/mentor-view" });
  }
  if (bootstrap.access?.is_admin || roles.includes("admin")) more.push({ key: "/withdrawn-cases", labelKey: "navWithdrawnCases", route: "/withdrawn-cases" });
  if (bootstrap.access?.is_admin || roles.includes("admin")) more.push({ key: "/admin/", labelKey: "homeAdminConsole", serverPath: "/admin/" });
  return { primary, more };
}

/** Every in-app route the sidebar or bottom bar can open (each `route` navEntries may return). */
export const SECTION_ROUTES: ReadonlySet<string> = new Set([
  "/", "/death-registration", "/collection", "/coding", "/reviewing", "/statistics", "/training", ...Object.values(TRAINING_ROUTES),
  "/organization", "/users", "/settings", "/mentoring", "/mentor-view", "/withdrawn-cases",
]);

/** The path of a root-stack route name: "index" is "/", "training/coding/index" is "/training/coding". */
export function stackRoutePath(name: string): string {
  return `/${name}`.replace(/\/index$/, "") || "/";
}

/**
 * Web only (digitva-hre5): a screen with a section opened above it is not rendered, so sidebar clicks do not pile
 * screens up on the page. The stack keeps its route: Back still reaches it, and it mounts afresh (the screen cache
 * shows its last answer at once). A screen under a case or form it opened is not a section's, so it stays as it was.
 */
export function coveredBySection(routes: ReadonlyArray<{ key: string; name: string }>, key: string): boolean {
  const index = routes.findIndex((route) => route.key === key);
  return index >= 0 && routes.slice(index + 1).some((route) => SECTION_ROUTES.has(stackRoutePath(route.name)));
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
    if (pathname === TRAINING_REPORTING_ROUTE) return TRAINING_ROUTES.interview;
    if (pathname === TRAINING_ROUTES.interview || pathname.startsWith(`${TRAINING_ROUTES.interview}/`)) return TRAINING_ROUTES.interview;
    if (pathname === TRAINING_ROUTES.coding || pathname.startsWith(`${TRAINING_ROUTES.coding}/`)) return TRAINING_ROUTES.coding;
    if (pathname === TRAINING_ROUTES.review || pathname.startsWith(`${TRAINING_ROUTES.review}/`)) return TRAINING_ROUTES.review;
    return "/training";
  }
  // The interview form and a case's details are reached from VA Interview.
  if (["/worklist", "/interview", "/case", "/form"].includes(pathname)) return "/collection";
  return ["/coding", "/reviewing", "/collection", "/death-registration", "/mentoring", "/statistics", "/data", "/organization", "/users", "/settings", "/withdrawn-cases"]
    .find((route) => pathname === route || pathname.startsWith(`${route}/`));
}

/**
 * The phone bottom bar: every signed-in screen except the case workspace (/workspace with a vaSid, coding/review
 * focus), the interview form (its case strip's back arrow leaves it; the bar only took height from the form) and the
 * pre-login routes.
 */
export function showBottomTabs(pathname: string, params: NavParams = {}): boolean {
  if (HEADERLESS_ROUTES.includes(pathname) || pathname === "/interview") return false;
  if (pathname === "/workspace" && first(params.vaSid)) return false;
  return true;
}
