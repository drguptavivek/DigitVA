import { useEffect, useMemo } from "react";
import { Platform } from "react-native";

import type { FormTheme } from "@drguptavivek/who-2022-va";

import { uiRadius, useTheme, type Theme } from "./theme";

/**
 * CSS custom properties of @drguptavivek/who-2022-va (web entry), all read from the `ui` tokens. A choice row uses
 * `surface` (fill), `control-border` (1px edge), `brand` (selected edge and dot), `brand-soft` (selected fill),
 * `ink-subtle` (text) and `radius-control`; the DORIS RadioRow reads the same tokens, so the two look identical.
 */
export function whoWebThemeVars({ ui }: Pick<Theme, "ui">): Record<string, string> {
  return {
    "--who-2022-web-color-brand": ui.primary,
    "--who-2022-web-color-brand-deep": ui.primaryPressed,
    "--who-2022-web-color-brand-soft": ui.accent,
    "--who-2022-web-color-on-accent": ui.primaryForeground,
    "--who-2022-web-color-canvas": ui.page,
    "--who-2022-web-color-surface": ui.background,
    "--who-2022-web-color-ink": ui.foreground,
    "--who-2022-web-color-ink-subtle": ui.foreground,
    "--who-2022-web-color-muted": ui.mutedForeground,
    "--who-2022-web-color-border": ui.border,
    "--who-2022-web-color-control-border": ui.input,
    "--who-2022-web-color-guidance": ui.warningText,
    "--who-2022-web-color-danger": ui.destructiveText,
    "--who-2022-web-color-danger-border": ui.destructiveText,
    "--who-2022-web-color-danger-strong": ui.destructiveText,
    "--who-2022-web-color-danger-soft": ui.destructiveSoft,
    "--who-2022-web-color-image-background": ui.muted,
    "--who-2022-web-radius-control": `${uiRadius.md}px`
  };
}

/** Colours of the WHO form engine (native and web `theme` prop), read from the same `ui` tokens, light and dark. */
export function whoFormTheme({ ui }: Pick<Theme, "ui">): FormTheme {
  return {
    primary: ui.primary,
    onPrimary: ui.primaryForeground,
    primarySoft: ui.accent,
    accent: ui.primaryPressed,
    surface: ui.card,
    surfaceAlt: ui.muted,
    border: ui.border,
    borderStrong: ui.input,
    text: ui.foreground,
    textMuted: ui.mutedForeground,
    danger: ui.destructiveText,
    dangerSoft: ui.destructiveSoft,
    success: ui.success,
    focus: ui.ring,
    scrim: "rgba(0, 0, 0, 0.5)"
  };
}

/** Web only: keep the package's choice controls on the app theme, light and dark. */
export function useWhoWebTheme() {
  const { ui, mode } = useTheme();
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const style = document.documentElement.style;
    style.setProperty("--digitva-page-background", ui.page);
    style.setProperty("--digitva-page-foreground", ui.foreground);
    style.colorScheme = mode;
    for (const [name, value] of Object.entries(whoWebThemeVars({ ui }))) style.setProperty(name, value);
  }, [ui, mode]);
}

/** The form theme of the current light or dark mode; a new object only when the mode changes. */
export function useWhoFormTheme(): FormTheme {
  const { ui } = useTheme();
  return useMemo(() => whoFormTheme({ ui }), [ui]);
}

/** Short labels (<= 18 characters) use 2 columns on phones and 3 elsewhere; long ones keep the width-based rule. */
export function choiceColumnsFor(width: number, labels: string[]): number {
  if (labels.every((label) => [...label].length <= 18)) return width < 480 ? 2 : 3;
  return width < 480 ? 1 : width < 900 ? 2 : 3;
}
