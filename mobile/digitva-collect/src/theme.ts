import { useCallback, useMemo, useSyncExternalStore } from "react";
import { Platform, useColorScheme, type TextStyle } from "react-native";

import {
  getUiTheme,
  peekUiTheme,
  setUiTheme,
  subscribeUiPreferences,
  type ThemePreference
} from "./preferences";

export type ColorMode = "light" | "dark";

/**
 * Brand blue, the only raw hexes outside the `ui` table. `primary` fills buttons and dots, `soft` is the
 * selected-row fill, `ring` the focus ring. Text on `soft` keeps >= 4.5:1 (ui-consistency contrast test).
 */
const brand = {
  light: { primary: "#1D4ED8", pressed: "#1E40AF", soft: "#E8F0FF", on: "#FFFFFF", ring: "#2563EB" },
  dark: { primary: "#78A9FF", pressed: "#A7C4FF", soft: "#1C3764", on: "#081429", ring: "#9CC0FF" }
} as const;

/** shadcn writes tokens as "H S% L%"; React Native needs hex, so the table below stays in shadcn's own numbers. */
export function hsl(h: number, s: number, l: number): string {
  const a = (s / 100) * Math.min(l / 100, 1 - l / 100);
  const channel = (n: number) => {
    const k = (n + h / 30) % 12;
    const value = l / 100 - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
    return Math.round(value * 255).toString(16).padStart(2, "0");
  };
  return `#${channel(0)}${channel(8)}${channel(4)}`.toUpperCase();
}

/** One accent family of a certificate line: bar/letter, header tint, chip fill and chip text. */
export type ChartToken = { bar: string; tint: string; soft: string; foreground: string };

export type UiTokens = {
  background: string; foreground: string;
  card: string; cardForeground: string;
  popover: string; popoverForeground: string;
  primary: string; primaryForeground: string;
  secondary: string; secondaryForeground: string;
  muted: string; mutedForeground: string;
  accent: string; accentForeground: string;
  destructive: string; destructiveForeground: string;
  /** Extension: destructive as text on `background`; shadcn's dark destructive is a fill, too dark to read as text. */
  destructiveText: string;
  /** Extensions: app page behind the cards, hover/pressed brand, success text, warning text, tinted danger fill, disabled glyphs. */
  page: string; primaryPressed: string; success: string; warningText: string; destructiveSoft: string; disabled: string;
  warning: string; warningForeground: string; warningBorder: string;
  border: string; input: string; ring: string;
  /** chart-1..5: Part I lines A-E; `chartPart2` is the slate Part II family. */
  chart: readonly ChartToken[];
  chartPart2: ChartToken;
};

const zincLight = {
  background: hsl(0, 0, 100), foreground: hsl(240, 10, 3.9),
  card: hsl(0, 0, 100), cardForeground: hsl(240, 10, 3.9),
  popover: hsl(0, 0, 100), popoverForeground: hsl(240, 10, 3.9),
  secondary: hsl(240, 4.8, 95.9), secondaryForeground: hsl(240, 5.9, 10),
  muted: hsl(240, 4.8, 95.9), mutedForeground: hsl(240, 3.8, 46.1),
  accent: hsl(240, 4.8, 95.9), accentForeground: hsl(240, 5.9, 10),
  // shadcn's hsl(0 84.2% 60.2%) gives 3.8:1 with its foreground; darkened to 72.2% / 50.6% to reach 4.5:1 for button and badge text.
  destructive: hsl(0, 72.2, 50.6), destructiveForeground: hsl(0, 0, 98),
  border: hsl(240, 5.9, 90), input: hsl(240, 5.9, 90)
};
const zincDark = {
  background: hsl(240, 10, 3.9), foreground: hsl(0, 0, 98),
  card: hsl(240, 10, 3.9), cardForeground: hsl(0, 0, 98),
  popover: hsl(240, 10, 3.9), popoverForeground: hsl(0, 0, 98),
  secondary: hsl(240, 3.7, 15.9), secondaryForeground: hsl(0, 0, 98),
  muted: hsl(240, 3.7, 15.9), mutedForeground: hsl(240, 5, 64.9),
  accent: hsl(240, 3.7, 15.9), accentForeground: hsl(0, 0, 98),
  destructive: hsl(0, 62.8, 30.6), destructiveForeground: hsl(0, 0, 98),
  border: hsl(240, 3.7, 15.9), input: hsl(240, 3.7, 15.9)
};

/**
 * shadcn/ui "zinc" semantic tokens for the DORIS editor (docs/current-state/doris-ui-tokens.md).
 * The single token source of the app: `palette` (old screens), `webPalette` and the WHO CSS variables are derived from it.
 * Neutrals are shadcn's; `primary` and `ring` are the DigitVA brand blue.
 */
export const ui: Record<ColorMode, UiTokens> = {
  light: {
    ...zincLight,
    // Blend with the app: tinted secondary/muted/accent and a stronger 1px border; cards stay white on the white page surface.
    page: "#F6F8FB",
    // `accent` is the brand-soft selected fill (choice rows, chips); text on it is `accentForeground`.
    secondary: "#EEF3F8", muted: "#EEF3F8", accent: brand.light.soft, accentForeground: "#10233F", mutedForeground: "#53657A",
    // `border` is the card/divider hairline; `input` the stronger (>= 3:1) edge of every control, choice row and outline button.
    border: "#CBD5E1", input: "#6B7C93",
    primary: brand.light.primary, primaryForeground: brand.light.on, primaryPressed: brand.light.pressed,
    destructiveText: "#B42318", destructiveSoft: "#FDECEC", success: "#1F7A4D", warningText: "#9A6700", disabled: "#8A99AA",
    warning: "#FEF3C7", warningForeground: "#3B2200", warningBorder: "#B45309",
    ring: brand.light.ring,
    chart: [
      { bar: "#C2185B", tint: "#FCE4EC", soft: "#F8BBD0", foreground: "#4A0A24" },
      { bar: "#B45309", tint: "#FEF3C7", soft: "#FCD34D", foreground: "#3B2200" },
      { bar: "#0F766E", tint: "#CCFBF1", soft: "#99F6E4", foreground: "#032F2B" },
      { bar: "#4338CA", tint: "#E0E7FF", soft: "#C7D2FE", foreground: "#1B1670" },
      { bar: "#7E22CE", tint: "#F3E8FF", soft: "#E9D5FF", foreground: "#3B0764" }
    ],
    chartPart2: { bar: "#475569", tint: "#F1F5F9", soft: "#E2E8F0", foreground: "#1E293B" }
  },
  dark: {
    ...zincDark,
    // The page and input fill are one tone (#131E2E); cards sit one step lighter, borders lighter than both.
    background: "#131E2E", page: "#131E2E", foreground: "#F4F7FB",
    card: "#1B2A3D", cardForeground: "#F4F7FB",
    popover: "#1B2A3D", popoverForeground: "#F4F7FB",
    secondary: "#243449", secondaryForeground: "#F4F7FB",
    muted: "#243449", mutedForeground: "#B5C2D1",
    accent: brand.dark.soft, accentForeground: "#F4F7FB",
    border: "#3E5068", input: "#7C90AB",
    primary: brand.dark.primary, primaryForeground: brand.dark.on, primaryPressed: brand.dark.pressed,
    destructiveText: "#FF8A80", destructiveSoft: "#4B2025", success: "#75D5A4", warningText: "#F5C76B", disabled: "#718097",
    warning: "#38280B", warningForeground: "#FFF3D1", warningBorder: "#FBBF24",
    ring: brand.dark.ring,
    chart: [
      { bar: "#F48FB1", tint: "#3B1A27", soft: "#6A2540", foreground: "#FFE4EE" },
      { bar: "#FBBF24", tint: "#38280B", soft: "#6B4A0C", foreground: "#FFF3D1" },
      { bar: "#2DD4BF", tint: "#0E3330", soft: "#145C55", foreground: "#D9FFF8" },
      { bar: "#A5B4FC", tint: "#22264F", soft: "#3B418D", foreground: "#EEF0FF" },
      { bar: "#D8B4FE", tint: "#2E1A47", soft: "#5B2A8C", foreground: "#F7ECFF" }
    ],
    chartPart2: { bar: "#94A3B8", tint: "#1E2733", soft: "#334155", foreground: "#F1F5F9" }
  }
};

export type RoleTone = "reporter" | "interviewer" | "supervisor" | "coder" | "reviewer" | "manager" | "pi" | "admin" | "neutral";
type RoleColours = { bg: string; border: string; fg: string };

/** Role chip colours: soft fill, strong border, text >= 4.5:1 on the fill (ui-token-contrast test). The name is always written too. */
export const roleTones: Record<ColorMode, Record<RoleTone, RoleColours>> = {
  light: {
    reporter: { bg: "#FFE4E6", border: "#E11D48", fg: "#9F1239" },
    interviewer: { bg: "#DBEAFE", border: "#2563EB", fg: "#1E3A8A" },
    supervisor: { bg: "#FEF3C7", border: "#D97706", fg: "#78350F" },
    coder: { bg: "#DCFCE7", border: "#16A34A", fg: "#14532D" },
    reviewer: { bg: "#EDE9FE", border: "#7C3AED", fg: "#4C1D95" },
    manager: { bg: "#CFFAFE", border: "#0891B2", fg: "#164E63" },
    pi: { bg: "#FAE8FF", border: "#C026D3", fg: "#701A75" },
    admin: { bg: "#CBD5E1", border: "#334155", fg: "#0F172A" },
    neutral: { bg: "#F1F5F9", border: "#64748B", fg: "#334155" }
  },
  dark: {
    reporter: { bg: "#4C1426", border: "#FB7185", fg: "#FFE4E6" },
    interviewer: { bg: "#172A52", border: "#60A5FA", fg: "#DBEAFE" },
    supervisor: { bg: "#46300A", border: "#FBBF24", fg: "#FEF3C7" },
    coder: { bg: "#0F3B22", border: "#4ADE80", fg: "#DCFCE7" },
    reviewer: { bg: "#2E1F5C", border: "#A78BFA", fg: "#EDE9FE" },
    manager: { bg: "#0B3A47", border: "#22D3EE", fg: "#CFFAFE" },
    pi: { bg: "#4A1559", border: "#E879F9", fg: "#FAE8FF" },
    admin: { bg: "#475569", border: "#CBD5E1", fg: "#F8FAFC" },
    neutral: { bg: "#243449", border: "#7C90AB", fg: "#E2E8F0" }
  }
};

const ROLE_TONE: Record<string, RoleTone> = {
  death_reporter: "reporter", interviewer: "interviewer", interview_supervisor: "supervisor", coder: "coder",
  reviewer: "reviewer", data_manager: "manager", project_pi: "pi", site_pi: "pi", admin: "admin"
};

/** The tone name of a role code; coding_tester, collaborators and unknown codes are neutral. */
export const roleToneName = (role: string): RoleTone => ROLE_TONE[role] ?? "neutral";
export const roleTone = (mode: ColorMode, role: string): RoleColours => roleTones[mode][roleToneName(role)];

/** shadcn --radius 0.5rem: lg = radius, md = radius - 2px, sm = radius - 4px. */
export const uiRadius = { lg: 8, md: 6, sm: 4, full: 9999 } as const;

export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48
} as const;

const webFontFamily = "system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

/** The one font-size scale: 12 caption, 14 body/label, 16 inputs and choice rows (no iOS zoom), 18/20/24/26 headings. */
export const fontSize = { caption: 12, body: 14, input: 16, headline: 18, heading: 20, title: 24, display: 26 } as const;

/** System fonts provide broad multi-script coverage; the web gets an explicit fallback stack. */
export const typography = {
  largeTitle: { fontSize: fontSize.display, lineHeight: 34, fontWeight: "700" as const },
  title: { fontSize: fontSize.title, lineHeight: 32, fontWeight: "700" as const },
  headline: { fontSize: fontSize.headline, lineHeight: 26, fontWeight: "600" as const },
  body: { fontSize: fontSize.input, lineHeight: 24, fontWeight: "400" as const },
  subhead: { fontSize: fontSize.body, lineHeight: 20, fontWeight: "400" as const },
  caption: { fontSize: fontSize.caption, lineHeight: 16, fontWeight: "400" as const }
} as const satisfies Record<string, TextStyle>;

/**
 * Text inside a control (button, chip, badge, tab). Android adds font padding above/below the glyphs, which
 * pushes Devanagari high or low in a pill; this removes it and centres the line box. Pair it with a line height
 * of at least 1.4x the font size (Devanagari matras need it) and symmetric vertical padding on the container.
 */
export const controlText = { includeFontPadding: false, textAlignVertical: "center", textAlign: "center" } as const satisfies TextStyle;

/** One radius scale (lg cards, md controls, sm chips/badges inside controls, full pills/dots). */
export const radius = uiRadius;

/** Control height 40, 44 minimum tap target on touch/phone, 1px borders, 12px gaps, 16px card padding. */
export const controls = {
  minHeight: 40,
  minTouchTarget: 44,
  borderWidth: 1,
  gap: spacing.sm,
  cardPadding: spacing.md,
  screenPadding: spacing.md,
  contentMaxWidth: 720,
  fontFamily: Platform.select({ web: webFontFamily, default: undefined })
} as const;

export type Palette = {
  background: string; surface: string; surfaceMuted: string; text: string; textMuted: string;
  border: string; borderStrong: string; accent: string; accentPressed: string; accentSoft: string; onAccent: string;
  danger: string; dangerSoft: string; success: string; warning: string; focus: string; disabled: string;
};

/** Old-system names (queue, shells, native routes) read from the `ui` tokens so no screen has a value of its own. */
const paletteOf = (t: UiTokens): Palette => ({
  background: t.page, surface: t.card, surfaceMuted: t.muted, text: t.foreground, textMuted: t.mutedForeground,
  border: t.border, borderStrong: t.input, accent: t.primary, accentPressed: t.primaryPressed, accentSoft: t.accent,
  onAccent: t.primaryForeground, danger: t.destructiveText, dangerSoft: t.destructiveSoft, success: t.success,
  warning: t.warningText, focus: t.ring, disabled: t.disabled
});

export const palette: Record<ColorMode, Palette> = { light: paletteOf(ui.light), dark: paletteOf(ui.dark) };

export type ButtonVariant = "default" | "secondary" | "outline" | "ghost" | "destructive";
export type ButtonSize = "sm" | "default" | "icon";

/** Fill, border and text colour of a button variant; shared by `Button` in src/ui.tsx and the DORIS kit. */
export const buttonTone = (t: UiTokens, variant: ButtonVariant) => ({
  default: { bg: t.primary, border: t.primary, fg: t.primaryForeground },
  secondary: { bg: t.secondary, border: t.secondary, fg: t.secondaryForeground },
  outline: { bg: t.background, border: t.input, fg: t.foreground },
  ghost: { bg: "transparent", border: "transparent", fg: t.foreground },
  destructive: { bg: t.destructive, border: t.destructive, fg: t.destructiveForeground }
})[variant];

/** Minimum button width (also chips): short labels such as "No" or "Add" never collapse into a circle. */
export const BUTTON_MIN_WIDTH = 72;

export type Theme = {
  mode: ColorMode;
  colors: Palette;
  spacing: typeof spacing;
  typography: typeof typography;
  radius: typeof radius;
  controls: typeof controls;
  ui: UiTokens;
};

export function getTheme(mode: ColorMode): Theme {
  return { mode, colors: palette[mode], spacing, typography, radius, controls, ui: ui[mode] };
}

/*
 * One shared preference store. Every useTheme() instance reads the same
 * in-memory value synchronously, so a remount never repaints with another
 * scheme. Web primes from localStorage at module load (before first render);
 * native renders the system scheme until its single async read lands.
 */
let storedPreference: ThemePreference = peekUiTheme() ?? "system";
const storeListeners = new Set<() => void>();

function applyPreference(next: ThemePreference) {
  if (next === storedPreference) return;
  storedPreference = next;
  for (const listener of storeListeners) listener();
}

if (peekUiTheme() === null) {
  void getUiTheme()
    // getUiPreference already lets a preference set while the read was in flight win.
    .then(applyPreference)
    .catch(() => undefined);
}
subscribeUiPreferences(() => {
  // Unknown (null) means keep the current value, e.g. a locale change before any theme read.
  const next = peekUiTheme();
  if (next !== null) applyPreference(next);
});

function subscribeStore(listener: () => void) {
  storeListeners.add(listener);
  return () => {
    storeListeners.delete(listener);
  };
}
const getStoredPreference = () => storedPreference;

/**
 * Theme hook. The stored preference is UI-only and defaults to the platform
 * colour scheme. Hindi and other scripts continue to use the platform font.
 */
export function useTheme(): Theme & {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => Promise<void>;
} {
  const systemScheme = useColorScheme();
  const preference = useSyncExternalStore(subscribeStore, getStoredPreference, getStoredPreference);
  const mode: ColorMode = preference === "system" ? (systemScheme === "dark" ? "dark" : "light") : preference;
  const theme = useMemo(() => getTheme(mode), [mode]);
  const updatePreference = useCallback(async (next: ThemePreference) => {
    applyPreference(next);
    await setUiTheme(next);
  }, []);
  return { ...theme, preference, setPreference: updatePreference };
}

/** Test seam: reset the shared store to an explicit preference. */
export function __setThemePreferenceForTest(next: ThemePreference) {
  applyPreference(next);
}
