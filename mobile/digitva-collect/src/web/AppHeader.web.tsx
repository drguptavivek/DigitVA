import { useGlobalSearchParams, useIsFocused, usePathname, useRouter } from "expo-router";
import React, { useCallback, useEffect, useId, useRef, useState, useSyncExternalStore } from "react";
import { useWindowDimensions } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { ui, useTheme } from "../theme";
import { AccountMenu } from "../workspace/AccountMenu.web";
import { ensureVendorCss } from "../workspace/vendorCss.web";
import { browserSessionStore, clearAllScroll } from "../workspace/viewState";
import { guardedNavigate, holdLinkClick, leaveDialogOpen, leavePage, leaveSaveFailed, saveAndLeave, stayOnPage, subscribeLeaveDialog } from "./navigationGuard";
import { activeTab, HEADERLESS_ROUTES, navEntries, showBottomTabs, type NavEntry, type NavParams } from "./navTabs";
import ProfileNudge from "./ProfileNudge.web";
import { rememberVisit } from "./roleHome";

// react-dom ships without types here (no @types/react-dom); the one call it is needed for, typed by hand.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createPortal } = require("react-dom") as { createPortal: (children: React.ReactNode, container: Element) => React.ReactElement };

const ROBOTO = "Roboto, Arial, sans-serif";
// The strip is brand blue with white text in both colour modes: the light-table pair is 6.7:1 and dark's soft pair is not.
const BAR = ui.light.primary;
const ON_BAR = ui.light.primaryForeground;
// Same phone breakpoint as the workspace layout and the DORIS kit.
const PHONE_BREAKPOINT = 768;
// common.tsx DESKTOP_BREAKPOINT: from here the left sidebar (which carries the logo) is a full 240px menu, below it a logoless rail.
const SIDEBAR_BREAKPOINT = 900;
// Routes that render without the sidebar: redirects, and a case workspace (vaSid); everything else is a WebShell screen.
const NO_SIDEBAR_ROUTES = ["/form", "/worklist"];
// Routes whose screen renders the header bar itself (AppHeaderBar, inside its scroller) so it scrolls away with the
// page; the interview pins only its case strip.
const SCROLLING_HEADER_ROUTES = ["/interview"];
const BAR_HEIGHT = 56;
const BOTTOM_BAR = `calc(${BAR_HEIGHT}px + env(safe-area-inset-bottom))`;
const h = React.createElement;

type NavItem = { key: string; href: string; to?: string; label: string; icon: string; newTab?: boolean; onActivate?: () => void };

/** Tabler outline icons (24 grid, stroke 2); paths are the tabler.io originals. */
const ICONS: Record<string, string[]> = {
  home: ["M5 12l-2 0l9 -9l9 9l-2 0", "M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7", "M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"],
  website: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0", "M3.6 9h16.8", "M3.6 15h16.8", "M11.5 3a17 17 0 0 0 0 18", "M12.5 3a17 17 0 0 1 0 18"],
  admin: ["M12 3a12 12 0 0 0 8.5 3a12 12 0 0 1 -8.5 15a12 12 0 0 1 -8.5 -15a12 12 0 0 0 8.5 -3"],
  coding: ["M14 3v4a1 1 0 0 0 1 1h4", "M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z", "M9 9l1 0", "M9 13l6 0", "M9 17l6 0"],
  reviewing: ["M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0", "M6 21v-2a4 4 0 0 1 4 -4h4", "M15 19l2 2l4 -4"],
  collection: ["M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2", "M9 3m0 2a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v0a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2z", "M9 12l.01 0", "M13 12l2 0", "M9 16l.01 0", "M13 16l2 0"],
  register: ["M12 5l0 14", "M5 12l14 0"],
  mentoring: ["M22 9l-10 -4l-10 4l10 4l10 -4v6", "M6 10.6v5.4a6 3 0 0 0 12 0v-5.4"],
  area: ["M3 7l6 -3l6 3l6 -3v13l-6 3l-6 -3l-6 3v-13", "M9 4v13", "M15 7v13"],
  data: ["M12 6m-8 0a8 3 0 1 0 16 0a8 3 0 1 0 -16 0", "M4 6v6a8 3 0 0 0 16 0v-6", "M4 12v6a8 3 0 0 0 16 0v-6"],
  organization: ["M3 21l18 0", "M9 8l1 0", "M9 12l1 0", "M9 16l1 0", "M14 8l1 0", "M14 12l1 0", "M14 16l1 0", "M5 21v-16a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v16"],
  settings: ["M4 10a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M6 4v4", "M6 12v8", "M10 16a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M12 4v10", "M12 18v2", "M16 7a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M18 4v1", "M18 9v11"],
  signOut: ["M14 8v-2a2 2 0 0 0 -2 -2h-7a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2 -2v-2", "M9 12h12l-3 -3", "M18 15l3 -3"],
  help: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0", "M12 17l0 .01", "M12 13.5a1.5 1.5 0 0 1 1 -1.5a2.6 2.6 0 1 0 -3 -4"],
  more: ["M5 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0", "M12 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0", "M19 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"],
};

/** Decorative: every use has a visible text label beside it. */
function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return h("svg", { "aria-hidden": true, focusable: "false", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", style: { flexShrink: 0 } },
    ICONS[name].map((d) => h("path", { key: d, d })));
}

/** Bottom-bar and sheet icon per navEntries key. */
const ENTRY_ICONS: Record<string, string> = {
  "/": "home", "/death-registration": "register", "/collection": "collection", "/coding": "coding", "/reviewing": "reviewing", "/area/": "area",
  "/organization": "organization", "/settings": "settings", website: "website", "/data-management/": "data", "/mentoring": "mentoring", "/admin/": "admin",
};

/**
 * Component CSS: pseudo-classes (hover, focus-visible) cannot be inline. A screen's contextual help trigger replaces
 * the Help link, so every page has one Help button. Colours are tokens; the ring is inset so no ancestor clips it.
 * Below the phone breakpoint every text field is 16px: iOS Safari zooms the page into a focused field under 16px and
 * stays zoomed, which clips the header, the form footer and the bottom bar on the right of every later screen. */
function css(tokens: typeof ui.light) {
  return `
.dva-tab{position:relative;display:inline-flex;align-items:center;gap:8px;box-sizing:border-box;min-height:44px;height:${BAR_HEIGHT}px;padding:0 14px;color:${ON_BAR};font:500 14px ${ROBOTO};text-decoration:none;background:transparent;border:0;cursor:pointer;flex-shrink:0;white-space:nowrap}
#digitva-app-header:has(#digitva-help-trigger) .dva-help-link{display:none!important}
.dva-tab:hover{background:color-mix(in srgb,${ON_BAR} 14%,transparent)}
.dva-tab:hover .dva-tab-in,.dva-tab:focus-visible .dva-tab-in{opacity:1!important}
.dva-tab:focus-visible,.dva-logo:focus-visible{outline:2px solid ${ON_BAR};outline-offset:-4px;border-radius:8px}
.dva-bottom-tab{position:relative;display:flex;flex:1;min-width:0;flex-direction:column;align-items:center;justify-content:center;gap:2px;box-sizing:border-box;height:${BAR_HEIGHT}px;padding:0 2px;color:${tokens.mutedForeground};font:500 12px ${ROBOTO};text-decoration:none;background:transparent;border:0;cursor:pointer}
.dva-bottom-label{max-width:100%;font-size:11px;line-height:13px;text-align:center;overflow-wrap:anywhere}
.dva-bottom-tab[aria-current=page],.dva-bottom-tab[aria-expanded=true]{color:${tokens.primary}}
.dva-bottom-tab:focus-visible,.dva-sheet-item:focus-visible{outline:2px solid ${tokens.ring};outline-offset:-3px;border-radius:8px}
.dva-sheet-item:hover{background:${tokens.accent}}
.dva-dialog-button:focus-visible{outline:2px solid ${tokens.ring};outline-offset:2px}
@media (max-width:${PHONE_BREAKPOINT - 1}px){input,textarea,select{font-size:16px!important}}`;
}

/**
 * Header link. With `to` and a handler, a plain left click navigates inside the app (the href stays real for
 * new-tab and right-click); modified clicks and a missing handler fall through to the browser. `newTab` opens the href in a new tab.
 * Both kinds of same-tab navigation go through the navigation guard; a new tab leaves nothing behind and skips it.
 */
export function HeaderLink({ href, children, to, onNavigate, newTab, current, label, className, style, role, onActivate }: {
  href: string; children?: React.ReactNode; to?: string; onNavigate?: (path: string) => void; newTab?: boolean; current?: boolean; label?: string;
  className?: string; style?: React.CSSProperties; role?: string; onActivate?: () => void;
}) {
  return h("a", {
    href, className, role,
    ...(newTab ? { target: "_blank", rel: "noopener" } : {}),
    ...(current ? { "aria-current": "page" } : {}),
    ...(label ? { "aria-label": label } : {}),
    onClick: to && onNavigate ? (event: React.MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      onActivate?.();
      guardedNavigate(() => onNavigate(to));
    } : (event: React.MouseEvent) => {
      if (!newTab && holdLinkClick(event, href, onActivate)) return;
      onActivate?.();
    },
    style: { display: "inline-flex", alignItems: "center", gap: 6, color: ON_BAR, fontFamily: ROBOTO, textDecoration: "none", flexShrink: 0, ...style },
  }, children);
}

/** The signed-in user's navEntries as links, for the phone bottom bar (the left sidebar renders the same list in common.tsx). */
function useNav() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useGlobalSearchParams() as NavParams;
  const { bootstrap, logout } = useAppState();
  const go = (path: string) => router.push(path as never);
  const hidden = !bootstrap || HEADERLESS_ROUTES.includes(pathname);
  const toItem = (entry: NavEntry): NavItem => {
    const base = { key: entry.key, label: t(entry.labelKey), icon: ENTRY_ICONS[entry.key] };
    if (entry.route) {
      const query = entry.params ? Object.entries(entry.params).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join("&") : "";
      const to = query ? `${entry.route}?${query}` : entry.route;
      return { ...base, href: `/app${to}`, to };
    }
    if (entry.serverPath) return { ...base, href: entry.serverPath, onActivate: () => rememberVisit(bootstrap!.user.user_id, entry.serverPath!) };
    return { ...base, href: entry.href!, newTab: true };
  };
  const entries = bootstrap && !hidden ? navEntries(bootstrap) : { primary: [], more: [] };
  const items = entries.primary.map(toItem);
  const more = entries.more.map(toItem);
  const current = activeTab(pathname, params);
  const signOut = async () => {
    await guardedNavigate(async () => {
      // Pinned scroll offsets are per case; drop them before the session ends.
      clearAllScroll(browserSessionStore());
      await logout?.();
    });
  };
  return { bootstrap, hidden, pathname, params, go, items, more, current, logout, signOut };
}

/** Escape, outside press and arrow-key roving for a menu panel; the same patterns as AccountMenu. */
function useMenu(onClose: (restoreFocus: boolean) => void, open: boolean, trigger?: React.RefObject<HTMLElement | null>) {
  const root = useRef<HTMLDivElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const items = () => Array.from(panel.current?.querySelectorAll<HTMLElement>("[role^='menuitem']") ?? []);
  useEffect(() => { if (open) items()[0]?.focus(); }, [open]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (event: PointerEvent) => {
      // The sheet and trigger count as inside even where no `root` wraps them (the phone sheet is fixed-position):
      // otherwise the pointerdown of a real click unmounts the sheet before its click lands.
      const inside = [root.current, panel.current, trigger?.current].some((el) => el?.contains(event.target as Node));
      if (event.target instanceof Node && !inside) onClose(false);
    };
    const leave = () => onClose(false);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("popstate", leave);
    return () => { document.removeEventListener("pointerdown", outside); window.removeEventListener("popstate", leave); };
  }, [open, onClose]);
  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { event.preventDefault(); onClose(true); return; }
    const list = items();
    if (!list.length) return;
    const at = list.indexOf(document.activeElement as HTMLElement);
    let next = -1;
    if (event.key === "ArrowDown") next = (at + 1) % list.length;
    else if (event.key === "ArrowUp") next = (at - 1 + list.length) % list.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = list.length - 1;
    else if (event.key === "Tab") next = event.shiftKey ? (at - 1 + list.length) % list.length : (at + 1) % list.length;
    if (next < 0) return;
    event.preventDefault();
    list[next].focus();
  };
  return { root, panel, onKeyDown };
}

const itemStyle = (tokens: typeof ui.light): React.CSSProperties => ({
  display: "flex", alignItems: "center", gap: 10, width: "100%", minHeight: 44, padding: "0 12px", boxSizing: "border-box",
  background: "transparent", color: tokens.popoverForeground, border: 0, borderRadius: 6, cursor: "pointer",
  fontFamily: ROBOTO, fontSize: 14, textAlign: "left", textDecoration: "none",
});

/** Menu entries: a link that navigates in-app (real href kept), or a button. */
function MenuEntries({ entries, go, close, tokens, extra }: { entries: NavItem[]; go: (path: string) => void; close: () => void; tokens: typeof ui.light; extra?: React.ReactNode }) {
  return h(React.Fragment, null,
    entries.map((item) => h(HeaderLink, {
      key: item.key, href: item.href, to: item.to, newTab: item.newTab, onNavigate: go, onActivate: () => { item.onActivate?.(); close(); }, role: "menuitem", className: "dva-sheet-item", style: { ...itemStyle(tokens), color: tokens.popoverForeground },
    }, h(Icon, { name: item.icon }), item.label)),
    extra);
}

/** The full logo (a 500x163 wordmark on a white background) on a white rounded plate, never cropped. */
const LOGO_RATIO = 500 / 163;
function LogoPlate({ height }: { height: number }) {
  return h("span", {
    "aria-hidden": true,
    style: { display: "block", width: Math.round(height * LOGO_RATIO), height, borderRadius: 8, flexShrink: 0, background: `${ui.light.card} url(/static/digitva_logo.png) center / contain no-repeat` },
  });
}

function Brand({ go, size }: { go: (path: string) => void; size: number }) {
  return h(HeaderLink, { href: "/app/", to: "/", onNavigate: go, label: "DigitVA home", className: "dva-logo", style: { minHeight: 44, borderRadius: 8 } },
    h(LogoPlate, { height: size }));
}

/** The Help link (hidden when the screen puts its own help trigger in the slot), the help slot and the account menu. */
function HeaderEnd({ nav }: { nav: ReturnType<typeof useNav> }) {
  const { bootstrap, pathname, logout, signOut } = nav;
  return h("span", { style: { display: "flex", alignItems: "center", alignSelf: "stretch", gap: 12, marginLeft: "auto" } },
    h(HeaderLink, { href: "/help", newTab: true, className: "dva-tab dva-help-link", style: { height: "100%" } },
      h("span", { className: "dva-tab-in", style: { display: "inline-flex", alignItems: "center", gap: 8, opacity: 0.8 } }, h(Icon, { name: "help" }), "Help")),
    h("span", { id: HELP_SLOT_ID, ref: setHelpSlot, style: { display: "contents" } }),
    // Keyed by route: the mounted-once header must close an open menu when the page changes.
    logout ? h(AccountMenu, { key: pathname, name: bootstrap!.user.name, onSignOut: signOut, onProfileClick: (event: React.MouseEvent) => holdLinkClick(event, "/profile/") }) : null);
}

/** Wide: Help and the account menu, plus the logo only where no sidebar shows its own. Navigation is the left sidebar only (common.tsx); case screens get home through the logo. */
function DesktopHeader({ nav, logo }: { nav: ReturnType<typeof useNav>; logo: boolean }) {
  return h("div", { style: { display: "flex", alignItems: "center", gap: 12, width: "100%", maxWidth: 1270, height: BAR_HEIGHT, margin: "0 auto", padding: "0 12px", boxSizing: "border-box" } },
    logo ? h(Brand, { go: nav.go, size: 40 }) : null,
    h(HeaderEnd, { nav }));
}

/** Phone: a 48px strip (logo, Help, account menu); the page title is the screen's own heading and navigation lives in the bottom bar. */
function PhoneHeader({ nav }: { nav: ReturnType<typeof useNav> }) {
  return h("div", { style: { display: "flex", alignItems: "center", gap: 10, width: "100%", height: 48, padding: "0 8px 0 12px", boxSizing: "border-box" } },
    h(Brand, { go: nav.go, size: 34 }),
    h(HeaderEnd, { nav }));
}

const HELP_SLOT_ID = "digitva-help-slot";

// The live help slot. The bar can move between the root layout and a screen's scroller (SCROLLING_HEADER_ROUTES), so
// HeaderHelpSlot follows the slot's ref instead of looking it up once; after a ref is dropped it falls back to
// whichever slot is still in the document.
let helpSlot: HTMLElement | null = null;
const helpSlotListeners = new Set<() => void>();
function setHelpSlot(node: HTMLElement | null) {
  if (node === helpSlot) return;
  helpSlot = node;
  helpSlotListeners.forEach((listener) => listener());
}
function currentHelpSlot(): HTMLElement | null {
  if (helpSlot?.isConnected) return helpSlot;
  return typeof document === "undefined" ? null : document.getElementById(HELP_SLOT_ID);
}
function subscribeHelpSlot(listener: () => void) {
  helpSlotListeners.add(listener);
  return () => { helpSlotListeners.delete(listener); };
}

/**
 * Renders a screen's help trigger into the app header, beside the account menu, so it never floats over page
 * toolbars. Inline (`inHeader` false) until the slot exists, on routes without the header, and while the screen is
 * not focused (the Stack keeps earlier screens mounted; only the focused one may own the slot). The slot node changes
 * when the header swaps between phone and desktop or moves into a screen's scroller, hence the subscription.
 */
export function HeaderHelpSlot({ children }: { children: (inHeader: boolean) => React.ReactNode }) {
  const focused = useIsFocused();
  const slot = useSyncExternalStore(subscribeHelpSlot, currentHelpSlot, () => null);
  return focused && slot?.isConnected ? createPortal(children(true), slot) : h(React.Fragment, null, children(false));
}

function useThemeTokens() {
  const theme = useTheme();
  return { tokens: theme.ui };
}

/**
 * The blue header bar. The root layout renders it sticky above the routes; a SCROLLING_HEADER_ROUTES screen renders
 * it itself (`sticky` false) as the first row of its scroller, so it scrolls away with the page.
 */
export function AppHeaderBar({ sticky = true }: { sticky?: boolean }) {
  const nav = useNav();
  const width = useWindowDimensions().width;
  const { tokens } = useThemeTokens();
  if (nav.hidden) return null;
  const caseOpen = nav.pathname === "/workspace" && Boolean(nav.params.vaSid);
  const sidebarLogo = width >= SIDEBAR_BREAKPOINT && !caseOpen && !NO_SIDEBAR_ROUTES.includes(nav.pathname);
  return h("header", {
    id: "digitva-app-header",
    style: { position: sticky ? "sticky" : "static", top: 0, zIndex: 40, flexShrink: 0, width: "100%", boxSizing: "border-box", background: BAR, color: ON_BAR, fontFamily: ROBOTO },
  }, h("style", null, css(tokens)), width < PHONE_BREAKPOINT ? h(PhoneHeader, { nav }) : h(DesktopHeader, { nav, logo: !sidebarLogo }));
}

/**
 * The one app header of every signed-in browser route, mounted once in the root layout. Sticky and in normal flow
 * above the routes, so a screen's own scroller never has to know about it; on SCROLLING_HEADER_ROUTES the screen
 * renders the bar instead. The profile nudge and the leave dialog stay here on every route.
 */
export default function AppHeader() {
  const nav = useNav();
  useEffect(() => { if (nav.bootstrap) ensureVendorCss(); }, [nav.bootstrap]);
  if (nav.hidden) return null;
  return h(React.Fragment, null,
    SCROLLING_HEADER_ROUTES.includes(nav.pathname) ? null : h(AppHeaderBar),
    h(ProfileNudge),
    h(LeaveDialog),
  );
}

/**
 * The navigation guard's leave dialog (navigationGuard.ts), mounted once with the header. An alertdialog: focus starts
 * on Stay and stays inside it, Escape is Stay, and focus returns where it was. The interview autosaves, so the dialog
 * only opens while a save is pending or the last one failed, and its body says which. Save and leave stays open (busy)
 * until the save settles; a failed save closes it and the screen shows the error.
 */
export function LeaveDialog() {
  const open = useSyncExternalStore(subscribeLeaveDialog, leaveDialogOpen, leaveDialogOpen);
  const { tokens } = useThemeTokens();
  const [busy, setBusy] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const stay = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return undefined;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    stay.current?.focus();
    return () => { if (previous?.isConnected) previous.focus(); };
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        if (!busy) stayOnPage();
        return;
      }
      if (event.key !== "Tab") return;
      const list = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>("button:not([disabled])") ?? []);
      event.preventDefault();
      if (!list.length) return;
      const at = list.indexOf(document.activeElement as HTMLButtonElement);
      list[event.shiftKey ? (at <= 0 ? list.length - 1 : at - 1) : (at + 1) % list.length].focus();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, busy]);

  if (!open) return null;
  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await saveAndLeave();
    } finally {
      setBusy(false);
    }
  };
  const button = (primary: boolean): React.CSSProperties => ({
    width: "100%", minHeight: 44, padding: "0 16px", borderRadius: 8, cursor: "pointer", fontFamily: ROBOTO, fontSize: 16, fontWeight: 600,
    border: `1px solid ${primary ? tokens.primary : tokens.border}`, background: primary ? tokens.primary : "transparent",
    color: primary ? tokens.primaryForeground : tokens.popoverForeground,
  });
  return h("div", {
    // Presses outside the dialog do nothing: the choice is one of its three buttons.
    onMouseDown: (event: React.MouseEvent) => { if (event.target === event.currentTarget) event.preventDefault(); },
    style: { position: "fixed", inset: 0, zIndex: 60, display: "flex", alignItems: "center", justifyContent: "center", padding: 16, boxSizing: "border-box", background: "rgba(0,0,0,0.45)" },
  },
  h("div", {
    ref: panel, role: "alertdialog", "aria-modal": true, "aria-labelledby": "digitva-leave-title", "aria-describedby": "digitva-leave-body",
    style: { width: "100%", maxWidth: 420, padding: 20, boxSizing: "border-box", display: "flex", flexDirection: "column", gap: 12, background: tokens.popover, color: tokens.popoverForeground, border: `1px solid ${tokens.border}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.28)", fontFamily: ROBOTO },
  },
  h("h2", { id: "digitva-leave-title", style: { margin: 0, fontSize: 18, lineHeight: "24px" } }, t("leaveTitle")),
  h("p", { id: "digitva-leave-body", style: { margin: "0 0 4px", fontSize: 16, lineHeight: "22px" } }, leaveSaveFailed() ? t("leaveBodyFailed") : t("leaveBody")),
  h("button", { ref: stay, type: "button", className: "dva-dialog-button", disabled: busy, onClick: stayOnPage, style: button(true) }, t("leaveStay")),
  h("button", { type: "button", className: "dva-dialog-button", "aria-busy": busy, onClick: () => void save(), style: button(false) }, busy ? t("leaveSaving") : t("leaveSaveAndLeave")),
  h("button", { type: "button", className: "dva-dialog-button", disabled: busy, onClick: leavePage, style: { ...button(false), color: tokens.destructiveText } }, t("leaveWithoutSaving"))));
}

/** True while the on-screen keyboard is up: the visual viewport is much shorter than the tallest height seen. */
function useKeyboardOpen(): boolean {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const viewport = typeof window === "undefined" ? undefined : window.visualViewport;
    if (!viewport) return undefined;
    let baseline = Math.max(window.innerHeight, viewport.height);
    let width = viewport.width;
    const check = () => {
      if (viewport.width !== width) { width = viewport.width; baseline = Math.max(window.innerHeight, viewport.height); } // rotation
      baseline = Math.max(baseline, viewport.height);
      setOpen(baseline - viewport.height > 150);
    };
    viewport.addEventListener("resize", check);
    return () => viewport.removeEventListener("resize", check);
  }, []);
  return open;
}

/**
 * Phone bottom tab bar (< 768px): the primary navEntries and a More sheet with the rest and Sign out, the same items
 * as the wide left sidebar. Shown on every signed-in screen except a case in focus mode (`showBottomTabs`). Renders an in-flow spacer of its own
 * height so no screen is covered.
 */
export function BottomTabs() {
  const nav = useNav();
  const width = useWindowDimensions().width;
  const keyboard = useKeyboardOpen();
  const { tokens } = useThemeTokens();
  const id = useId();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = useCallback((restore = true) => { setOpen(false); if (restore) trigger.current?.focus(); }, []);
  const menu = useMenu(close, open, trigger);
  const { pathname, params, go, items, more, current, signOut } = nav;
  useEffect(() => setOpen(false), [pathname]);
  if (nav.hidden || width >= PHONE_BREAKPOINT || keyboard || !showBottomTabs(pathname, params)) return null;

  const moreCurrent = more.some((item) => item.key === current);
  const entry = itemStyle(tokens);
  return h(React.Fragment, null,
    h("div", { "aria-hidden": true, style: { height: BOTTOM_BAR, flexShrink: 0 } }),
    h("style", null, css(tokens)),
    open ? h("div", { onClick: () => close(false), style: { position: "fixed", inset: 0, zIndex: 34 } }) : null,
    open ? h("div", {
      ref: menu.panel, id, role: "menu", "aria-label": t("navMore"), onKeyDown: menu.onKeyDown,
      style: { position: "fixed", left: 8, right: 8, bottom: `calc(${BOTTOM_BAR} + 8px)`, zIndex: 36, maxHeight: "60vh", overflowY: "auto", padding: 6, boxSizing: "border-box", background: tokens.popover, color: tokens.popoverForeground, border: `1px solid ${tokens.border}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.28)" },
    }, h(MenuEntries, {
      entries: more, go, close: () => close(false), tokens,
      extra: h(React.Fragment, null,
        h("div", { role: "separator", style: { height: 1, margin: "4px 0", background: tokens.border } }),
        h("button", { type: "button", role: "menuitem", className: "dva-sheet-item", style: { ...entry, color: tokens.destructiveText }, onClick: () => void signOut() }, h(Icon, { name: "signOut" }), t("signOut"))),
    })) : null,
    h("nav", {
      "aria-label": "Primary",
      style: { position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 35, display: "flex", height: BOTTOM_BAR, paddingBottom: "env(safe-area-inset-bottom)", boxSizing: "border-box", background: tokens.card, borderTop: `1px solid ${tokens.border}` },
    },
    items.map((item) => h(HeaderLink, { key: item.key, href: item.href, to: item.to, onNavigate: go, onActivate: item.onActivate, current: current === item.key, className: "dva-bottom-tab", style: { color: undefined, flexDirection: "column", gap: 2 } },
      current === item.key ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 8, right: 8, top: 0, height: 3, borderRadius: 4, background: tokens.primary } }) : null,
      h(Icon, { name: item.icon, size: 22 }), h("span", { className: "dva-bottom-label" }, item.label))),
    h("button", {
      ref: trigger, type: "button", className: "dva-bottom-tab", "aria-haspopup": "menu", "aria-expanded": open, "aria-controls": open ? id : undefined,
      onClick: () => (open ? close() : setOpen(true)), ...(moreCurrent ? { "data-current": "true" } : {}),
    },
    open || moreCurrent ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 8, right: 8, top: 0, height: 3, borderRadius: 4, background: tokens.primary } }) : null,
    h(Icon, { name: "more", size: 22 }), h("span", { className: "dva-bottom-label" }, t("navMore")))));
}
