/**
 * Role home for the web app: which screens and actions a user has access to on
 * the Home / Dashboard (`/app/`), per-project role and action helpers, and
 * last-visit / session helpers.
 */
import type { AccessProject, ClientBootstrap } from "../client/api";
import type { StringKey } from "../i18n";

/** Expo screens a user can open; the browser remembers these as last visits. */
export const ROLE_SCREENS = ["/coding", "/reviewing", "/collection", "/death-registration", "/mentoring"];
/** Server-rendered pages a data manager can open; also remembered as last visits. */
export const SERVER_SCREENS = ["/area/", "/data-management/"];

type RoleBootstrap = Pick<ClientBootstrap, "access" | "capabilities">;

export interface HomeActionItem {
  key: string;
  labelKey: StringKey;
  pathname?: string;
  params?: Record<string, string>;
  serverPath?: string;
}

const ROLE_KEY_MAP: Record<string, StringKey> = {
  admin: "role_admin",
  project_pi: "role_project_pi",
  site_pi: "role_site_pi",
  data_manager: "role_data_manager",
  interviewer: "role_interviewer",
  death_reporter: "role_death_reporter",
  interview_supervisor: "role_interview_supervisor",
  coder: "role_coder",
  coding_tester: "role_coding_tester",
  reviewer: "role_reviewer",
  collaborator: "role_collaborator",
  collaborator_pii: "role_collaborator_pii",
};

export function roleLabelKey(role: string): StringKey {
  return ROLE_KEY_MAP[role] ?? "role_collaborator";
}

/** True when the user holds any active role, admin flag, mentoring membership, or project grant. */
export function hasAnyRoleOrProject(bootstrap: RoleBootstrap): boolean {
  const roles = bootstrap.access?.roles ?? [];
  const projects = bootstrap.access?.projects ?? [];
  const hasMentoring = Boolean(
    bootstrap.capabilities?.mentoring ||
      bootstrap.access?.account?.mentor?.member ||
      (bootstrap.access?.account?.mentor?.admin_of?.length ?? 0) > 0,
  );
  return Boolean(
    bootstrap.access?.is_admin ||
      hasMentoring ||
      roles.length > 0 ||
      projects.length > 0,
  );
}

function isInternalContainerSite(name: string | undefined): boolean {
  if (!name) return true;
  return /^sites_in_project_/i.test(name.trim());
}

/** Format a single project grant as a translated role + scope badge string. */
export function describeProjectGrant(
  grant: AccessProject["grants"][number],
  sites: AccessProject["sites"] | undefined,
  translate: (key: StringKey, params?: Record<string, string | number>) => string,
): string {
  const roleKey = ROLE_KEY_MAP[grant.role];
  const roleText = roleKey ? translate(roleKey) : grant.role;
  let scopeText = translate("homeScopeProject");
  if (grant.scope === "project_site") {
    const matchedSite = (sites ?? []).find((s) => s.site_id === grant.site_id);
    const siteName = matchedSite?.site_name ?? grant.site_id ?? "";
    if (!isInternalContainerSite(siteName) && !isInternalContainerSite(grant.site_id)) {
      scopeText = translate("homeScopeSite", { site: siteName });
    }
  } else if (grant.scope === "org_unit") {
    scopeText = translate("homeScopeUnit", { unit: grant.unit_name ?? grant.org_unit_id ?? "" });
  }
  const base = translate("homeRoleWithScope", { role: roleText, scope: scopeText });
  return grant.active ? base : `${base}${translate("homeRoleInactiveSuffix")}`;
}

/**
 * Format all grants in a project as one line per (role, active), combining
 * multiple assigned area units into "Within Area: Unit A, Unit B" or "All".
 */
export function describeProjectGrants(
  grants: AccessProject["grants"] | undefined,
  sites: AccessProject["sites"] | undefined,
  translate: (key: StringKey, params?: Record<string, string | number>) => string,
): string[] {
  const list = grants ?? [];
  const grouped = new Map<
    string,
    { role: string; active: boolean; allScope: boolean; areas: string[]; singleGrant: AccessProject["grants"][number] }
  >();
  for (const grant of list) {
    const key = `${grant.role}:${grant.active ? "1" : "0"}`;
    let entry = grouped.get(key);
    if (!entry) {
      entry = { role: grant.role, active: grant.active, allScope: false, areas: [], singleGrant: grant };
      grouped.set(key, entry);
    }
    if (grant.scope === "project") {
      entry.allScope = true;
    } else if (grant.scope === "project_site") {
      const matchedSite = (sites ?? []).find((s) => s.site_id === grant.site_id);
      const siteName = matchedSite?.site_name ?? grant.site_id ?? "";
      if (isInternalContainerSite(siteName) || isInternalContainerSite(grant.site_id)) {
        entry.allScope = true;
      } else if (!entry.areas.includes(siteName)) {
        entry.areas.push(siteName);
      }
    } else if (grant.scope === "org_unit") {
      const unitName = grant.unit_name ?? grant.org_unit_id ?? "";
      if (unitName && !entry.areas.includes(unitName)) {
        entry.areas.push(unitName);
      }
    }
  }
  const lines: string[] = [];
  for (const entry of grouped.values()) {
    if (!entry.allScope && entry.areas.length <= 1) {
      lines.push(describeProjectGrant(entry.singleGrant, sites, translate));
      continue;
    }
    const roleKey = ROLE_KEY_MAP[entry.role];
    const roleText = roleKey ? translate(roleKey) : entry.role;
    const scopeText = entry.allScope
      ? translate("homeScopeProject")
      : translate("homeScopeUnit", { unit: entry.areas.join(", ") });
    const base = translate("homeRoleWithScope", { role: roleText, scope: scopeText });
    lines.push(entry.active ? base : `${base}${translate("homeRoleInactiveSuffix")}`);
  }
  return lines;
}

/**
 * Per-project action buttons ordered by the 5 pipeline processes:
 * 1. Death Register -> 2. Interview -> 3. Coding -> 4. Review -> 5. Organization / Summary Reports.
 */
export function projectActionItems(project: AccessProject, effectiveRoles: string[]): HomeActionItem[] {
  const items: HomeActionItem[] = [];
  const grants = project.grants ?? [];
  const hasInterview = (project.actions?.interview?.length ?? 0) > 0;
  if ((project.actions?.register_death?.length ?? 0) > 0) {
    items.push({ key: "registerDeath", labelKey: "registerDeath", pathname: "/death-registration" });
    if (!hasInterview) {
      items.push({
        key: "myRegisteredDeaths",
        labelKey: "myRegisteredDeaths",
        pathname: "/death-registration",
        params: { view: "mine" },
      });
    }
  }
  if (hasInterview) {
    items.push({ key: "collection", labelKey: "navCollection", pathname: "/collection" });
  }
  if (
    grants.some(
      (g) => g.active && (g.role === "coder" || g.role === "coding_tester") && g.codes !== false,
    )
  ) {
    items.push({
      key: "coding",
      labelKey: "navCoding",
      pathname: "/coding",
      params: { project: project.project_id },
    });
  }
  if (grants.some((g) => g.active && g.role === "reviewer" && g.codes !== false)) {
    items.push({
      key: "reviewing",
      labelKey: "navReview",
      pathname: "/reviewing",
      params: { project: project.project_id },
    });
  }
  const hasSupervisoryGrant = grants.some(
    (g) =>
      g.active &&
      (g.role === "interview_supervisor" ||
        g.role === "data_manager" ||
        g.role === "project_pi" ||
        (g.role === "site_pi" && g.scope === "org_unit")),
  );
  if (
    hasSupervisoryGrant &&
    (effectiveRoles.includes("interview_supervisor") || effectiveRoles.includes("data_manager"))
  ) {
    items.push({ key: "supervision", labelKey: "homeCtaNeedsDecision", pathname: "/death-registration", params: { view: "mine", preset: "supervision" } });
  }
  if (project.has_tree) {
    items.push({ key: "organization", labelKey: "navOrganization", pathname: "/organization" });
  }
  return items;
}

/**
 * Role screens the user may open, in landing order. Supervisors work in the
 * Deaths tab, where their project registers deaths (capabilities.supervision, from the server's supervises_deaths).
 */
export function roleScreens(bootstrap: RoleBootstrap): string[] {
  const roles = bootstrap.access?.roles ?? [];
  const screens: string[] = [];
  if (roles.some((role) => role === "coder" || role === "coding_tester")) screens.push("/coding");
  if (roles.includes("reviewer")) screens.push("/reviewing");
  if (bootstrap.capabilities?.intake) screens.push("/collection");
  if (bootstrap.capabilities?.registerDeath || bootstrap.capabilities?.registeredDeaths || bootstrap.capabilities?.supervision) screens.push("/death-registration");
  if (
    bootstrap.capabilities?.mentoring ||
    bootstrap.access?.account?.mentor?.member ||
    (bootstrap.access?.account?.mentor?.admin_of?.length ?? 0) > 0
  ) {
    screens.push("/mentoring");
  }
  return screens;
}

/** Server pages the user may open from the home and the menu. */
export function serverScreens(bootstrap: RoleBootstrap): string[] {
  return (bootstrap.access?.roles ?? []).includes("data_manager") ? [...SERVER_SCREENS] : [];
}

/**
 * Primary role screen for a user (used when a caller explicitly resolves a
 * preferred workflow screen).
 */
export function homeLanding(bootstrap: RoleBootstrap, lastVisit: string | undefined): string | undefined {
  const allowed = [...roleScreens(bootstrap), ...serverScreens(bootstrap)];
  if (lastVisit && allowed.includes(lastVisit)) return lastVisit;
  return roleScreens(bootstrap)[0] ?? serverScreens(bootstrap)[0];
}

function lastVisitKey(userId: string): string {
  return `digitva.lastVisit.${userId}`;
}

const FIRST_LOAD_PREFIX = "digitva.homeLanded.";

function firstLoadKey(userId: string): string {
  return `${FIRST_LOAD_PREFIX}${userId}`;
}

export function readLastVisit(userId: string): string | undefined {
  try {
    return window.localStorage.getItem(lastVisitKey(userId)) ?? undefined;
  } catch {
    return undefined;
  }
}

export function rememberVisit(userId: string, path: string): void {
  try {
    window.localStorage.setItem(lastVisitKey(userId), path);
  } catch {
    // Storage unavailable: ignore.
  }
}

/** True on the first home load of this browser session for this user. Unavailable storage counts as first. */
export function claimFirstHomeLoad(userId: string): boolean {
  try {
    const key = firstLoadKey(userId);
    if (window.sessionStorage.getItem(key)) return false;
    window.sessionStorage.setItem(key, "1");
    return true;
  } catch {
    return true;
  }
}

/**
 * Clear every user's first-load flag at sign-out or session expiry.
 */
export function resetFirstHomeLoad(): void {
  try {
    const storage = window.sessionStorage;
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index);
      if (key?.startsWith(FIRST_LOAD_PREFIX)) storage.removeItem(key);
    }
  } catch {
    // Nothing stored to clear.
  }
}

/** Open a server page, remembering it first. */
export function openServerPage(userId: string, path: string): void {
  rememberVisit(userId, path);
  window.location.assign(path);
}
