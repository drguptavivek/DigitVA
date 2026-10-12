import { useGlobalSearchParams, usePathname, useRouter } from "expo-router";
import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { useWindowDimensions } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { ui, useTheme } from "../theme";
import { AccountMenu } from "../workspace/AccountMenu.web";
import { ensureVendorCss } from "../workspace/vendorCss.web";
import { browserSessionStore, clearAllScroll } from "../workspace/viewState";
import { activeTab, HEADERLESS_ROUTES, MORE_WIDTH, showBottomTabs, tabsThatFit, type NavParams } from "./navTabs";
import { roleScreens, serverScreens } from "./roleHome";

const ROBOTO = "Roboto, Arial, sans-serif";
// The strip is brand blue with white text in both colour modes: the light-table pair is 6.7:1 and dark's soft pair is not.
const BAR = ui.light.primary;
const ON_BAR = ui.light.primaryForeground;
// Same phone breakpoint as the workspace layout and the DORIS kit.
const PHONE_BREAKPOINT = 768;
const BAR_HEIGHT = 56;
const BOTTOM_BAR = `calc(${BAR_HEIGHT}px + env(safe-area-inset-bottom))`;
const h = React.createElement;

type NavItem = { key: string; href: string; to?: string; label: string; short: string; icon: string; newTab?: boolean };

/** Tabler outline icons (24 grid, stroke 2); paths are the tabler.io originals. */
const ICONS: Record<string, string[]> = {
  coding: ["M14 3v4a1 1 0 0 0 1 1h4", "M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2z", "M9 9l1 0", "M9 13l6 0", "M9 17l6 0"],
  reviewing: ["M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0", "M6 21v-2a4 4 0 0 1 4 -4h4", "M15 19l2 2l4 -4"],
  collection: ["M9 5h-2a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-12a2 2 0 0 0 -2 -2h-2", "M9 3m0 2a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v0a2 2 0 0 1 -2 2h-2a2 2 0 0 1 -2 -2z", "M9 12l.01 0", "M13 12l2 0", "M9 16l.01 0", "M13 16l2 0"],
  register: ["M12 5l0 14", "M5 12l14 0"],
  supervision: ["M11.46 20.846a12 12 0 0 1 -7.96 -14.846a12 12 0 0 0 8.5 -3a12 12 0 0 0 8.5 3a12 12 0 0 1 -.09 7.06", "M15 19l2 2l4 -4"],
  area: ["M3 7l6 -3l6 3l6 -3v13l-6 3l-6 -3l-6 3v-13", "M9 4v13", "M15 7v13"],
  data: ["M12 6m-8 0a8 3 0 1 0 16 0a8 3 0 1 0 -16 0", "M4 6v6a8 3 0 0 0 16 0v-6", "M4 12v6a8 3 0 0 0 16 0v-6"],
  organization: ["M3 21l18 0", "M9 8l1 0", "M9 12l1 0", "M9 16l1 0", "M14 8l1 0", "M14 12l1 0", "M14 16l1 0", "M5 21v-16a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v16"],
  settings: ["M4 10a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M6 4v4", "M6 12v8", "M10 16a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M12 4v10", "M12 18v2", "M16 7a2 2 0 1 0 4 0a2 2 0 0 0 -4 0", "M18 4v1", "M18 9v11"],
  profile: ["M8 7a4 4 0 1 0 8 0a4 4 0 0 0 -8 0", "M6 21v-2a4 4 0 0 1 4 -4h4a4 4 0 0 1 4 4v2"],
  signOut: ["M14 8v-2a2 2 0 0 0 -2 -2h-7a2 2 0 0 0 -2 2v12a2 2 0 0 0 2 2h7a2 2 0 0 0 2 -2v-2", "M9 12h12l-3 -3", "M18 15l3 -3"],
  help: ["M12 12m-9 0a9 9 0 1 0 18 0a9 9 0 1 0 -18 0", "M12 17l0 .01", "M12 13.5a1.5 1.5 0 0 1 1 -1.5a2.6 2.6 0 1 0 -3 -4"],
  more: ["M5 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0", "M12 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0", "M19 12m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"],
};

/** Decorative: every use has a visible text label beside it. */
function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return h("svg", { "aria-hidden": true, focusable: "false", width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", style: { flexShrink: 0 } },
    ICONS[name].map((d) => h("path", { key: d, d })));
}

const ROLE_ITEMS: Record<string, () => Omit<NavItem, "key" | "href" | "to">> = {
  "/coding": () => ({ label: "VA Coding", short: t("navCoding"), icon: "coding" }),
  "/reviewing": () => ({ label: "VA Review", short: t("navReview"), icon: "reviewing" }),
  "/collection": () => ({ label: t("reportedDeaths"), short: t("reportedDeaths"), icon: "collection" }),
  "/death-registration": () => ({ label: t("registerDeath"), short: t("registerDeath"), icon: "register" }),
  "/supervision": () => ({ label: t("supervisionTitle"), short: t("supervisionTitle"), icon: "supervision" }),
};
const SERVER_ITEMS: Record<string, () => Omit<NavItem, "key" | "href" | "to">> = {
  "/area/": () => ({ label: t("navArea"), short: t("navArea"), icon: "area" }),
  "/data-management/": () => ({ label: t("navDataManagement"), short: t("navDataManagement"), icon: "data" }),
};

/** Component CSS: pseudo-classes (hover, focus-visible) cannot be inline. Colours are tokens; the ring is inset so no ancestor clips it. */
function css(tokens: typeof ui.light) {
  return `
.dva-tab{position:relative;display:inline-flex;align-items:center;gap:8px;box-sizing:border-box;min-height:44px;height:${BAR_HEIGHT}px;padding:0 14px;color:${ON_BAR};font:500 14px ${ROBOTO};text-decoration:none;background:transparent;border:0;cursor:pointer;flex-shrink:0;white-space:nowrap}
.dva-tab:hover{background:color-mix(in srgb,${ON_BAR} 14%,transparent)}
.dva-tab:hover .dva-tab-in,.dva-tab:focus-visible .dva-tab-in{opacity:1!important}
.dva-tab:focus-visible,.dva-logo:focus-visible{outline:2px solid ${ON_BAR};outline-offset:-4px;border-radius:8px}
.dva-bottom-tab{position:relative;display:flex;flex:1;min-width:0;flex-direction:column;align-items:center;justify-content:center;gap:2px;box-sizing:border-box;height:${BAR_HEIGHT}px;padding:0 2px;color:${tokens.mutedForeground};font:500 12px ${ROBOTO};text-decoration:none;background:transparent;border:0;cursor:pointer}
.dva-bottom-tab[aria-current=page],.dva-bottom-tab[aria-expanded=true]{color:${tokens.primary}}
.dva-bottom-tab:focus-visible,.dva-sheet-item:focus-visible{outline:2px solid ${tokens.ring};outline-offset:-3px;border-radius:8px}
.dva-sheet-item:hover{background:${tokens.accent}}`;
}

/**
 * Header link. With `to` and a handler, a plain left click navigates inside the app (the href stays real for
 * new-tab and right-click); modified clicks and a missing handler fall through to the browser. `newTab` opens the href in a new tab.
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
      onNavigate(to);
    } : onActivate,
    style: { display: "inline-flex", alignItems: "center", gap: 6, color: ON_BAR, fontFamily: ROBOTO, textDecoration: "none", flexShrink: 0, ...style },
  }, children);
}

/** Items of the signed-in role, shared by the desktop tabs and the phone bottom bar. */
function useNav() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useGlobalSearchParams() as NavParams;
  const { bootstrap, logout } = useAppState();
  const go = (path: string) => router.push(path as never);
  const hidden = !bootstrap || HEADERLESS_ROUTES.includes(pathname);
  const items: NavItem[] = [];
  const more: NavItem[] = [];
  if (bootstrap && !hidden) {
    for (const route of roleScreens(bootstrap).filter((r) => ROLE_ITEMS[r])) items.push({ key: route, href: `/app${route}`, to: route, ...ROLE_ITEMS[route]() });
    for (const route of serverScreens(bootstrap)) items.push({ key: route, href: route, ...SERVER_ITEMS[route]() });
    more.push({ key: "/organization", href: "/app/organization", to: "/organization", label: t("navOrganization"), short: t("navOrganization"), icon: "organization" });
    more.push({ key: "/settings", href: "/app/settings", to: "/settings", label: t("navSettings"), short: t("navSettings"), icon: "settings" });
  }
  const current = activeTab(pathname, params);
  const signOut = async () => {
    // Pinned scroll offsets are per case; drop them before the session ends.
    clearAllScroll(browserSessionStore());
    await logout?.();
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
      key: item.key, href: item.href, to: item.to, newTab: item.newTab, onNavigate: go, onActivate: close, role: "menuitem", className: "dva-sheet-item", style: { ...itemStyle(tokens), color: tokens.popoverForeground },
    }, h(Icon, { name: item.icon }), item.label)),
    extra);
}

/** Desktop overflow: the tabs that did not fit, in a dropdown under a "More" tab. */
function MoreTab({ entries, go, current, tokens }: { entries: NavItem[]; go: (path: string) => void; current: boolean; tokens: typeof ui.light }) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  const close = useCallback((restore = true) => { setOpen(false); if (restore) trigger.current?.focus(); }, []);
  const menu = useMenu(close, open);
  return h("div", { ref: menu.root, style: { position: "relative", flexShrink: 0 } },
    h("button", {
      ref: trigger, type: "button", className: "dva-tab", "aria-haspopup": "menu", "aria-expanded": open, "aria-controls": open ? id : undefined,
      ...(current ? { "aria-current": "page" } : {}),
      onClick: () => (open ? close() : setOpen(true)),
    }, h("span", { className: "dva-tab-in", style: { display: "inline-flex", alignItems: "center", gap: 8, opacity: current ? 1 : 0.8 } }, h(Icon, { name: "more" }), "More"),
    current ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 0, right: 0, bottom: 0, height: 3, background: ON_BAR } }) : null),
    open ? h("div", {
      ref: menu.panel, id, role: "menu", "aria-label": "More", onKeyDown: menu.onKeyDown,
      style: { position: "absolute", left: 0, top: "calc(100% + 2px)", zIndex: 40, minWidth: 220, padding: 6, boxSizing: "border-box", background: tokens.popover, color: tokens.popoverForeground, border: `1px solid ${tokens.border}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.28)" },
    }, h(MenuEntries, { entries, go, close: () => close(false), tokens })) : null);
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

function DesktopHeader({ nav, width }: { nav: ReturnType<typeof useNav>; width: number }) {
  const { tokens } = useThemeTokens();
  const { bootstrap, pathname, go, items, more, current, logout, signOut } = nav;
  const tabs = [...items, more[0]];
  const hasName = width >= 480;
  const reserved = Math.min(width, 1270) - 24 - 150 - (hasName ? 224 : 44) - 20 - 100; // header padding, brand, account, gaps, Help tab -> room for the tabs
  const fit = tabsThatFit(tabs.map((tab) => tab.label), reserved, 0);
  const shown = tabs.slice(0, fit);
  const rest = [...tabs.slice(fit), more[1]];
  const moreCurrent = tabs.slice(fit).some((tab) => tab.key === current) || current === "/settings";
  return h("div", { style: { display: "flex", alignItems: "center", gap: 12, width: "100%", maxWidth: 1270, height: BAR_HEIGHT, margin: "0 auto", padding: "0 12px", boxSizing: "border-box" } },
    h(Brand, { go, size: 40 }),
    h("nav", { "aria-label": "Main", style: { display: "flex", alignItems: "center", alignSelf: "stretch", flex: 1, minWidth: 0, marginLeft: 8 } },
      shown.map((tab) => h(HeaderLink, {
        key: tab.key, href: tab.href, to: tab.to, onNavigate: go, current: current === tab.key, className: "dva-tab", style: { height: BAR_HEIGHT, gap: 8 },
      }, h("span", { className: "dva-tab-in", style: { display: "inline-flex", alignItems: "center", gap: 8, opacity: current === tab.key ? 1 : 0.8 } }, h(Icon, { name: tab.icon }), tab.label),
      current === tab.key ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 0, right: 0, bottom: 0, height: 3, background: ON_BAR } }) : null)),
      h(MoreTab, { entries: rest, go, current: moreCurrent, tokens }),
      h(HeaderLink, { href: "/help", newTab: true, className: "dva-tab", style: { height: BAR_HEIGHT, marginLeft: "auto" } },
        h("span", { className: "dva-tab-in", style: { display: "inline-flex", alignItems: "center", gap: 8, opacity: 0.8 } }, h(Icon, { name: "help" }), "Help"))),
    // Keyed by route: the mounted-once header must close an open menu when the page changes.
    logout ? h(AccountMenu, { key: pathname, name: bootstrap!.user.name, onSignOut: signOut }) : null);
}

/** Phone: a 48px strip (logo, account menu); the page title is the screen's own heading and navigation lives in the bottom bar. */
function PhoneHeader({ nav }: { nav: ReturnType<typeof useNav> }) {
  const { bootstrap, pathname, go, logout, signOut } = nav;
  return h("div", { style: { display: "flex", alignItems: "center", gap: 10, width: "100%", height: 48, padding: "0 8px 0 12px", boxSizing: "border-box" } },
    h(HeaderLink, { href: "/app/", to: "/", onNavigate: go, label: "DigitVA home", className: "dva-logo", style: { minHeight: 44, borderRadius: 8 } },
      h(LogoPlate, { height: 34 })),
    h("span", { "aria-hidden": true, style: { flex: 1 } }),
    logout ? h(AccountMenu, { key: pathname, name: bootstrap!.user.name, onSignOut: signOut }) : null);
}

function useThemeTokens() {
  const theme = useTheme();
  return { tokens: theme.ui };
}

/**
 * The one app header of every signed-in browser route, mounted once in the root layout. Sticky and in normal flow
 * above the routes, so a screen's own scroller never has to know about it.
 */
export default function AppHeader() {
  const nav = useNav();
  const width = useWindowDimensions().width;
  const { tokens } = useThemeTokens();
  useEffect(() => { if (nav.bootstrap) ensureVendorCss(); }, [nav.bootstrap]);
  if (nav.hidden) return null;
  return h("header", {
    id: "digitva-app-header",
    style: { position: "sticky", top: 0, zIndex: 40, flexShrink: 0, width: "100%", boxSizing: "border-box", background: BAR, color: ON_BAR, fontFamily: ROBOTO },
  }, h("style", null, css(tokens)), width < PHONE_BREAKPOINT ? h(PhoneHeader, { nav }) : h(DesktopHeader, { nav, width }));
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
 * Phone bottom tab bar (< 768px): the first two destinations of the role, Help and a More sheet. Shown on top-level
 * screens only (`showBottomTabs`). Renders an in-flow spacer of its own height so no screen is covered.
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

  // Role screens get the bar (up to four); Reports/dashboard (server pages), Organization, Settings and Help live in More.
  const isRole = (item: NavItem) => item.key in ROLE_ITEMS;
  const primary = items.filter(isRole).slice(0, 4);
  const help: NavItem = { key: "/help", href: "/help", newTab: true, label: "Help", short: "Help", icon: "help" };
  const rest = [...items.filter((item) => !primary.includes(item)), ...more, help];
  const moreCurrent = rest.some((item) => item.key === current);
  const entry = itemStyle(tokens);
  return h(React.Fragment, null,
    h("div", { "aria-hidden": true, style: { height: BOTTOM_BAR, flexShrink: 0 } }),
    h("style", null, css(tokens)),
    open ? h("div", { onClick: () => close(false), style: { position: "fixed", inset: 0, zIndex: 34 } }) : null,
    open ? h("div", {
      ref: menu.panel, id, role: "menu", "aria-label": "More", onKeyDown: menu.onKeyDown,
      style: { position: "fixed", left: 8, right: 8, bottom: `calc(${BOTTOM_BAR} + 8px)`, zIndex: 36, maxHeight: "60vh", overflowY: "auto", padding: 6, boxSizing: "border-box", background: tokens.popover, color: tokens.popoverForeground, border: `1px solid ${tokens.border}`, borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.28)" },
    }, h(MenuEntries, {
      entries: rest, go, close: () => close(false), tokens,
      extra: h(React.Fragment, null,
        h("div", { role: "separator", style: { height: 1, margin: "4px 0", background: tokens.border } }),
        h("a", { role: "menuitem", href: "/profile/", className: "dva-sheet-item", style: entry }, h(Icon, { name: "profile" }), "Profile"),
        h("button", { type: "button", role: "menuitem", className: "dva-sheet-item", style: { ...entry, color: tokens.destructiveText }, onClick: () => void signOut() }, h(Icon, { name: "signOut" }), "Sign out")),
    })) : null,
    h("nav", {
      "aria-label": "Primary",
      style: { position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 35, display: "flex", height: BOTTOM_BAR, paddingBottom: "env(safe-area-inset-bottom)", boxSizing: "border-box", background: tokens.card, borderTop: `1px solid ${tokens.border}` },
    },
    primary.map((item) => h(HeaderLink, { key: item.key, href: item.href, to: item.to, onNavigate: go, current: current === item.key, className: "dva-bottom-tab", style: { color: undefined, flexDirection: "column", gap: 2 } },
      current === item.key ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 8, right: 8, top: 0, height: 3, borderRadius: 4, background: tokens.primary } }) : null,
      h(Icon, { name: item.icon, size: 22 }), item.short)),
    h("button", {
      ref: trigger, type: "button", className: "dva-bottom-tab", "aria-haspopup": "menu", "aria-expanded": open, "aria-controls": open ? id : undefined,
      onClick: () => (open ? close() : setOpen(true)), ...(moreCurrent ? { "data-current": "true" } : {}),
    },
    open || moreCurrent ? h("span", { "aria-hidden": true, style: { position: "absolute", left: 8, right: 8, top: 0, height: 3, borderRadius: 4, background: tokens.primary } }) : null,
    h(Icon, { name: "more", size: 22 }), "More")));
}

export { MORE_WIDTH };
