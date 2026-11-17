import { useMemo } from "react";

import { ui, uiHighContrast, useTheme, type ColorMode, type UiTokens } from "../theme";

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
  selected: string; onSelected: string; demo: string; demoBorder: string; onDemo: string; chipBg: string; blocked: string;
  disabledBg: string; disabledBorder: string; disabledText: string;
  yes: string; no: string; onYes: string; onNo: string;
  warnBg: string; warnBorder: string; warnText: string;
  viewerBg: string; closeBg: string; closeText: string;
};

/**
 * Every surface, border and text colour is a `ui` token, normal or high contrast. Yes/No fills, the selected category
 * and the DEMO badge are the phone's (CategoryPanel.tsx QuestionRow, PhoneSectionRail, DemoBadge).
 */
const webOf = (mode: ColorMode, t: UiTokens): WebPalette => {
  const light = mode === "light";
  return {
    primary: t.primary, bar: light ? t.primary : t.accent, onBar: light ? t.primaryForeground : t.foreground,
    page: t.page, card: t.card, muted: t.muted, header: t.muted,
    text: t.foreground, textMuted: t.mutedForeground,
    border: t.border, borderSoft: t.secondary, cardEdge: t.border,
    pillBorder: t.border, pillBg: t.accent,
    selected: t.primary, onSelected: t.primaryForeground, demo: t.warning, demoBorder: t.warningBorder, onDemo: t.warningForeground, chipBg: t.muted, blocked: t.destructiveText,
    disabledBg: t.muted, disabledBorder: t.border, disabledText: t.mutedForeground,
    yes: t.destructive, onYes: t.destructiveForeground, no: t.success, onNo: t.primaryForeground,
    warnBg: t.warning, warnBorder: t.warningBorder, warnText: t.warningForeground,
    viewerBg: t.page, closeBg: light ? t.card : t.foreground, closeText: light ? t.foreground : t.page
  };
};

/** The normal palette; `webPaletteHighContrast` is the same names on the high-contrast tokens. */
export const webPalette: Record<ColorMode, WebPalette> = { light: webOf("light", ui.light), dark: webOf("dark", ui.dark) };
export const webPaletteHighContrast: Record<ColorMode, WebPalette> = { light: webOf("light", uiHighContrast.light), dark: webOf("dark", uiHighContrast.dark) };

/** Palette of the active UI theme (light/dark, system by default; high contrast when the switch is on). */
export function useWebPalette(): WebPalette {
  const { mode, highContrast } = useTheme();
  return (highContrast ? webPaletteHighContrast : webPalette)[mode];
}

/** `make` must be a module-level function so the styles are rebuilt only when the mode changes. */
export function useWebStyles<T>(make: (w: WebPalette) => T): readonly [T, WebPalette] {
  const w = useWebPalette();
  return useMemo(() => [make(w), w] as const, [make, w]);
}
