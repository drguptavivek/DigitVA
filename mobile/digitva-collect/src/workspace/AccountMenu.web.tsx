import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import { useWindowDimensions } from "react-native";

import type { ThemePreference } from "../preferences";
import { useTheme } from "../theme";
import { useWebPalette } from "./webPalette";

export type AccountMenuProps = {
  /** Display name from /api/v1/me; shown in the menu heading and (wide) beside the avatar. Never logged. */
  name: string;
  /** Ends the session (POST logout with CSRF, in the app state). A rejection keeps the menu open with an error. Omitted on the desktop station, which has no session to end. */
  onSignOut?: () => Promise<void>;
  /** Plain-click handler of the Profile link (a full Flask page); true when it held the navigation (the menu closes). */
  onProfileClick?: (event: React.MouseEvent) => boolean;
};

// Below this the display name is hidden and only the initials circle stays.
const NAME_MIN_WIDTH = 480;
const ROBOTO = "Roboto, Arial, sans-serif";
const THEMES: Array<{ value: ThemePreference; label: string }> = [
  { value: "light", label: "Light" },
  { value: "dark", label: "Dark" },
  { value: "system", label: "System" },
];

export function initialsOf(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : (parts[0] ?? "").slice(0, 2);
  return letters.toUpperCase() || "?";
}

/** Right-aligned account control of the workspace header: Profile, Open web version, Theme, Help, Sign out. */
export function AccountMenu({ name, onSignOut, onProfileClick }: AccountMenuProps) {
  const theme = useTheme();
  const w = useWebPalette();
  const { width } = useWindowDimensions();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const showName = width >= NAME_MIN_WIDTH;
  const tokens = theme.ui;

  const close = useCallback((restoreFocus = true) => {
    setOpen(false);
    setError("");
    if (restoreFocus) trigger.current?.focus();
  }, []);

  const items = () => Array.from(panel.current?.querySelectorAll<HTMLElement>("[role^='menuitem']") ?? []);

  useEffect(() => {
    if (open) items()[0]?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target)) close(false);
    };
    const leave = () => close(false);
    document.addEventListener("pointerdown", outside);
    window.addEventListener("popstate", leave);
    window.addEventListener("hashchange", leave);
    return () => {
      document.removeEventListener("pointerdown", outside);
      window.removeEventListener("popstate", leave);
      window.removeEventListener("hashchange", leave);
    };
  }, [open, close]);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    const list = items();
    if (!list.length) return;
    const at = list.indexOf(document.activeElement as HTMLElement);
    let next = -1;
    if (event.key === "ArrowDown") next = (at + 1) % list.length;
    else if (event.key === "ArrowUp") next = (at - 1 + list.length) % list.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = list.length - 1;
    else if (event.key === "Tab") next = event.shiftKey ? (at - 1 + list.length) % list.length : (at + 1) % list.length; // trap
    if (next < 0) return;
    event.preventDefault();
    list[next].focus();
  };

  const signOut = async () => {
    setBusy(true);
    setError("");
    try {
      await onSignOut?.();
      setOpen(false);
    } catch {
      setError("Could not sign out. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const itemStyle: React.CSSProperties = {
    display: "flex", alignItems: "center", gap: 10, width: "100%", minHeight: 44, padding: "0 12px", boxSizing: "border-box",
    background: "transparent", color: tokens.popoverForeground, border: 0, borderRadius: 6, cursor: "pointer",
    fontFamily: ROBOTO, fontSize: 14, textAlign: "left", textDecoration: "none",
  };
  const label: React.CSSProperties = { padding: "8px 12px 2px", color: tokens.mutedForeground, fontFamily: ROBOTO, fontSize: 12, fontWeight: 700 };
  const rule: React.CSSProperties = { height: 1, margin: "4px 0", background: tokens.border };
  const h = React.createElement;
  const menuId = `account-menu-${id}`;

  const content = open ? h("div", {
    ref: panel,
    onKeyDown,
    style: {
      position: "absolute", right: 0, top: "calc(100% + 6px)", zIndex: 40, width: 260, maxWidth: "92vw", padding: 6, boxSizing: "border-box",
      background: tokens.popover, color: tokens.popoverForeground, border: `1px solid ${tokens.border}`, borderRadius: 8,
      boxShadow: "0 8px 24px rgba(0,0,0,0.28)",
    },
  },
  h("div", { style: { padding: "8px 12px", fontFamily: ROBOTO, fontSize: 14, fontWeight: 700, overflowWrap: "anywhere" } }, name),
  h("div", { style: rule }),
  h("div", { id: menuId, role: "menu", "aria-label": "Account" },
    h("a", { role: "menuitem", href: "/profile/", onClick: (event: React.MouseEvent) => { if (onProfileClick?.(event)) close(false); }, style: itemStyle }, "Profile"),
    h("a", { role: "menuitem", href: "/vaindex", target: "_blank", rel: "noopener", "aria-label": "Open web version (opens in a new tab)", style: itemStyle },
      "Open web version",
      h("svg", { "aria-hidden": true, width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", style: { marginLeft: "auto" } },
        h("path", { d: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" }))),
    h("div", { role: "presentation", style: label }, "Theme"),
    THEMES.map((option) => h("button", {
      key: option.value, type: "button", role: "menuitemradio", "aria-checked": theme.preference === option.value,
      style: { ...itemStyle, background: theme.preference === option.value ? tokens.accent : "transparent", fontWeight: theme.preference === option.value ? 700 : 400 },
      onClick: () => { void theme.setPreference(option.value); close(); },
    }, option.label, theme.preference === option.value ? h("span", { "aria-hidden": true, style: { marginLeft: "auto" } }, "✓") : null)),
    h("div", { style: rule, role: "separator" }),
    h("a", { role: "menuitem", href: "/help", target: "_blank", rel: "noopener", style: itemStyle }, "Help"),
    onSignOut ? h("button", { type: "button", role: "menuitem", disabled: busy, onClick: () => void signOut(), style: { ...itemStyle, color: tokens.destructiveText } }, busy ? "Signing out…" : "Sign out") : null,
  ),
  error ? h("div", { role: "alert", style: { padding: "6px 12px", color: tokens.destructiveText, fontFamily: ROBOTO, fontSize: 12 } }, error) : null,
  ) : null;

  return h("div", { ref: root, style: { position: "relative", marginLeft: "auto" } },
      h("button", {
        ref: trigger, type: "button", "aria-haspopup": "menu", "aria-expanded": open, "aria-controls": open ? menuId : undefined,
        "aria-label": `Account menu, ${name}`,
        onClick: () => (open ? close() : setOpen(true)),
        style: {
          display: "flex", alignItems: "center", gap: 8, minHeight: 44, minWidth: 44, padding: "0 4px", background: "transparent", border: 0,
          color: w.onBar, cursor: "pointer", fontFamily: ROBOTO, fontSize: 12, fontWeight: 700,
        },
      },
      h("span", { "aria-hidden": true, style: { display: "inline-flex", alignItems: "center", justifyContent: "center", width: 32, height: 32, borderRadius: "50%", background: "rgba(255,255,255,0.22)", border: "1px solid rgba(255,255,255,0.6)", fontSize: 12 } }, initialsOf(name)),
      showName ? h("span", { style: { maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, name) : null),
      content);
}
