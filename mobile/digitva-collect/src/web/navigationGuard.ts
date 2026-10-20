/**
 * One guard against leaving a browser screen that holds unsaved work. The screen registers it while focused
 * (useNavigationGuard); every navigation control (left menu, phone bottom bar and More sheet, header logo and
 * links, Sign out, the screen's own back button, router back) routes through guardedNavigate. While the guard is
 * dirty a navigation opens the leave dialog (AppHeader's LeaveDialog) instead of running; otherwise it runs at once.
 */
import { useIsFocused, useNavigation } from "expo-router";
import { useEffect, useRef } from "react";

export type NavigationGuard = {
  /** True when leaving now would lose changes. */
  isDirty(): boolean;
  /** Saves the work; resolves true once saved, false when it failed (the screen shows the error). */
  save(): Promise<boolean>;
  /** True when the last save failed (the dialog then asks the user to check the connection); absent means never. */
  saveFailed?(): boolean;
};

let guard: NavigationGuard | undefined;
let pending: (() => unknown) | undefined;
// Set once the user chose to leave, so the navigation that follows (and its beforeunload) is not asked again.
let released = false;
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((listener) => listener());
const browserWindow = () => (typeof window !== "undefined" && typeof window.addEventListener === "function" ? window : undefined);

function shouldAsk(): boolean {
  return !!guard && !released && guard.isDirty();
}

function onBeforeUnload(event: BeforeUnloadEvent) {
  if (!shouldAsk()) return;
  event.preventDefault();
  event.returnValue = "";
}

/** Installs `next` as the one guard; the returned function removes it (and closes its dialog). */
export function registerNavigationGuard(next: NavigationGuard): () => void {
  guard = next;
  released = false;
  browserWindow()?.addEventListener("beforeunload", onBeforeUnload);
  return () => {
    if (guard !== next) return;
    browserWindow()?.removeEventListener("beforeunload", onBeforeUnload);
    guard = undefined;
    released = false;
    if (pending) {
      pending = undefined;
      notify();
    }
  };
}

/**
 * Runs `perform` now (returning its result) when nothing would be lost. Otherwise opens the leave dialog, which
 * runs it after Leave or a successful Save; a request while the dialog is open is dropped (no stacked dialogs).
 */
export function guardedNavigate<T>(perform: () => T): T | undefined {
  if (!shouldAsk()) return perform();
  if (!pending) {
    pending = perform;
    notify();
  }
  return undefined;
}

/**
 * For a same-tab link the browser follows itself (a Flask page, Profile): holds a plain left click while the guard
 * would ask and follows `href` once the user leaves. Any other click is left to the browser.
 */
export function holdLinkClick(
  event: { defaultPrevented: boolean; button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean; preventDefault(): void },
  href: string,
  before?: () => void,
): boolean {
  if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !shouldAsk()) return false;
  event.preventDefault();
  guardedNavigate(() => {
    before?.();
    window.location.assign(href);
  });
  return true;
}

function release() {
  const perform = pending;
  pending = undefined;
  notify();
  if (!perform) return;
  // ponytail: stays released until the guard unregisters (the screen unmounts or loses focus); a navigation that
  // goes nowhere (router.back with no history) leaves this screen unguarded until it is focused again.
  released = true;
  perform();
}

/** Whether the guarded screen's last save failed, for the leave dialog's wording. */
export function leaveSaveFailed(): boolean {
  return !!guard?.saveFailed?.();
}

export function leaveDialogOpen(): boolean {
  return pending !== undefined;
}

export function subscribeLeaveDialog(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Stay: close the dialog, drop the navigation. */
export function stayOnPage() {
  if (!pending) return;
  pending = undefined;
  notify();
}

/** Leave without saving. */
export function leavePage() {
  release();
}

/** Save and leave: leaves only after the save succeeds; on failure the dialog closes and the user stays. */
export async function saveAndLeave(): Promise<boolean> {
  const current = guard;
  const perform = pending;
  if (!current || !perform) return false;
  const saved = await current.save();
  if (guard !== current || pending !== perform) return false;
  if (!saved) {
    stayOnPage();
    return false;
  }
  release();
  return true;
}

/**
 * Registers `isDirty` and `save` as the navigation guard while the calling screen is focused (the Stack keeps an
 * earlier screen mounted under the next one), and asks before the router removes the screen (its back button,
 * router.back, browser Back where the router reports it). The callbacks may change between renders.
 */
export function useNavigationGuard(isDirty: () => boolean, save: () => Promise<boolean>, saveFailed?: () => boolean) {
  const focused = useIsFocused();
  const navigation = useNavigation();
  const latest = useRef({ isDirty, save, saveFailed });
  latest.current = { isDirty, save, saveFailed };

  useEffect(() => {
    if (!focused) return undefined;
    return registerNavigationGuard({
      isDirty: () => latest.current.isDirty(),
      save: () => latest.current.save(),
      saveFailed: () => !!latest.current.saveFailed?.(),
    });
  }, [focused]);

  useEffect(() => navigation.addListener("beforeRemove", (event) => {
    if (!shouldAsk()) return;
    event.preventDefault();
    guardedNavigate(() => navigation.dispatch(event.data.action));
  }), [navigation]);
}
