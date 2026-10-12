import { useEffect } from "react";
import { Platform } from "react-native";

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

/** Web only: keep the package's choice controls on the app theme, light and dark. */
export function useWhoWebTheme() {
  const { ui } = useTheme();
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return;
    const style = document.documentElement.style;
    for (const [name, value] of Object.entries(whoWebThemeVars({ ui }))) style.setProperty(name, value);
  }, [ui]);
}

/** Short labels (<= 18 characters) use 2 columns on phones and 3 elsewhere; long ones keep the width-based rule. */
export function choiceColumnsFor(width: number, labels: string[]): number {
  if (labels.every((label) => [...label].length <= 18)) return width < 480 ? 2 : 3;
  return width < 480 ? 1 : width < 900 ? 2 : 3;
}
