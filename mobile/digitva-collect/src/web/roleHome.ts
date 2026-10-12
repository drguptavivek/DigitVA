/**
 * Role home for the web app: which screen a user lands on after sign-in, and
 * the last screen each browser remembers. Storage is a convenience only; when
 * it is unavailable the user simply lands on their first role screen.
 */
import type { ClientBootstrap } from "../client/api";

/** Expo screens a user can land on; the browser remembers these as last visits. */
export const ROLE_SCREENS = ["/coding", "/reviewing", "/collection", "/death-registration", "/supervision"];
/** Server-rendered pages a data manager lands on; also remembered as last visits. */
export const SERVER_SCREENS = ["/area/", "/data-management/"];

type RoleBootstrap = Pick<ClientBootstrap, "access" | "capabilities">;

/**
 * Role screens the user may open, in landing order. Supervision keys on the
 * interview_supervisor role: data_manager also sets the supervision capability.
 */
export function roleScreens(bootstrap: RoleBootstrap): string[] {
  const roles = bootstrap.access.roles;
  const screens: string[] = [];
  if (roles.some((role) => role === "coder" || role === "coding_tester")) screens.push("/coding");
  if (roles.includes("reviewer")) screens.push("/reviewing");
  if (bootstrap.capabilities.intake) screens.push("/collection");
  if (bootstrap.capabilities.registerDeath || bootstrap.capabilities.registeredDeaths) screens.push("/death-registration");
  if (roles.includes("interview_supervisor")) screens.push("/supervision");
  return screens;
}

/** Server pages the user may open from the home and the menu. */
export function serverScreens(bootstrap: RoleBootstrap): string[] {
  return bootstrap.access.roles.includes("data_manager") ? [...SERVER_SCREENS] : [];
}

/**
 * The first-load landing: the remembered screen when the user still has
 * access to it, else the first role screen, else Area for a data manager only.
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
    // Storage unavailable: the next sign-in lands on the first role screen.
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
 * Clear every user's first-load flag at sign-out or session expiry, so the next
 * sign-in in this tab lands again. Clears all users: the caller may not know the
 * user any more once the session has gone.
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

/** Open a server page, remembering it first so the next sign-in returns there. */
export function openServerPage(userId: string, path: string): void {
  rememberVisit(userId, path);
  window.location.assign(path);
}
