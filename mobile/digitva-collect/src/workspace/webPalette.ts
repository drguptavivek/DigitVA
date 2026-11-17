import { useMemo } from "react";

import { ui, useTheme, type ColorMode } from "../theme";

/**
 * Colours of the browser case workspace: the Petrol theme the phone uses (owner decision 2026-11-17). Every pair that
 * carries text keeps >= 4.5:1 in both modes; every value is a `ui` token (src/theme.ts) so the page, the DORIS card,
 * these screens and the phone workspace read as one surface.
 */
export type WebPalette = {
  primary: string; bar: string; onBar: string;
  page: string; card: string; muted: string; header: string;
  text: string; textMuted: string;
  border: string; borderSoft: string; cardEdge: string;
  pillBorder: string; pillBg: string;
  selected: string; demo: string; chipBg: string; blocked: string;
  disabledBg: string; disabledBorder: string; disabledText: string;
  yes: string; no: string; onYes: string; onNo: string;
  warnBg: string; warnBorder: string; warnText: string;
  viewerBg: string; closeBg: string; closeText: string;
};

/** Every surface, border and text colour is a `ui` token. Yes/No fills are the phone's (CategoryPanel.tsx AnswerRow). */
const webOf = (mode: ColorMode): WebPalette => {
  const t = ui[mode];
  const light = mode === "light";
  return {
    primary: t.primary, bar: light ? t.primary : t.accent, onBar: light ? t.primaryForeground : t.foreground,
    page: t.page, card: t.card, muted: t.muted, header: t.muted,
    text: t.foreground, textMuted: t.mutedForeground,
    border: t.border, borderSoft: t.secondary, cardEdge: t.border,
    pillBorder: t.border, pillBg: t.accent,
    selected: light ? t.primary : t.accent, demo: t.destructive, chipBg: t.muted, blocked: t.destructiveText,
    disabledBg: t.muted, disabledBorder: t.border, disabledText: t.mutedForeground,
    yes: t.destructive, onYes: t.destructiveForeground, no: t.success, onNo: t.primaryForeground,
    warnBg: t.warning, warnBorder: t.warningBorder, warnText: t.warningForeground,
    viewerBg: t.page, closeBg: light ? t.card : t.foreground, closeText: light ? t.foreground : t.page
  };
};

export const webPalette: Record<ColorMode, WebPalette> = { light: webOf("light"), dark: webOf("dark") };

/** Palette of the active UI theme (light/dark, system by default). */
export function useWebPalette(): WebPalette {
  return webPalette[useTheme().mode];
}

/** `make` must be a module-level function so the styles are rebuilt only when the mode changes. */
export function useWebStyles<T>(make: (w: WebPalette) => T): readonly [T, WebPalette] {
  const w = useWebPalette();
  return useMemo(() => [make(w), w] as const, [make, w]);
}
