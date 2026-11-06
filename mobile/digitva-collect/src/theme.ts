import { useCallback, useMemo, useSyncExternalStore } from "react";
import { AccessibilityInfo, Platform, useColorScheme, useWindowDimensions, type TextStyle } from "react-native";

import {
  getUiHighContrast,
  getUiTextSize,
  getUiTheme,
  peekUiHighContrast,
  peekUiTextSize,
  peekUiTheme,
  setUiHighContrast,
  setUiTextSize,
  setUiTheme,
  subscribeUiPreferences,
  type HighContrastPreference,
  type TextSizePreference,
  type ThemePreference
} from "./preferences";
import { petrolHex } from "./themeColors";

export type ColorMode = "light" | "dark";

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
  /** Petrol extensions: `primaryTint` (selected rows, secondary buttons; the same value as `accent`), `attention`
   * (the amber badge fill, only ever with `onAttention` ink text) and its row tint, the success tint, and the
   * inset hairline between rows of a card. */
  primaryTint: string; attention: string; onAttention: string; attentionTint: string; successTint: string; separator: string;
  /** Modal backdrop behind dialogs and sheets. */
  scrim: string;
  /** Box shadow of popovers, menus and dialogs (web CSS `boxShadow`); native uses `elevation`. */
  shadow: string;
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
 * Names are shadcn's; the values are the Petrol theme (src/themeColors.ts, OKLCH source), normal or high contrast.
 */
function petrolTokens(petrolLight: ReturnType<typeof petrolHex>, petrolDark: ReturnType<typeof petrolHex>): Record<ColorMode, UiTokens> {
  return {
  light: {
    ...zincLight,
    // Petrol: cards (white) on the canvas; inputs are white fills on the canvas with no edge until focused.
    page: petrolLight.canvas, background: petrolLight.card, card: petrolLight.card, popover: petrolLight.card,
    foreground: petrolLight.text, cardForeground: petrolLight.text, popoverForeground: petrolLight.text,
    // `secondary`/`muted` are the neutral fill (chips, segmented track); `accent` is the primary tint (selected fill).
    secondary: petrolLight.neutralFill, secondaryForeground: petrolLight.text, muted: petrolLight.neutralFill,
    accent: petrolLight.primaryTint, accentForeground: petrolLight.text, mutedForeground: petrolLight.secondaryText,
    // `border` is the inset hairline; `input` the >= 3:1 edge of checkboxes, radios and outline buttons.
    border: petrolLight.separator, input: petrolLight.controlEdge,
    primary: petrolLight.primary, primaryForeground: petrolLight.onPrimary, primaryPressed: petrolLight.primaryPressed,
    destructive: petrolLight.error, destructiveForeground: petrolLight.onPrimary,
    destructiveText: petrolLight.error, destructiveSoft: petrolLight.errorTint, success: petrolLight.success,
    warningText: petrolLight.guidance, disabled: petrolLight.disabled,
    warning: petrolLight.accentTint, warningForeground: petrolLight.text, warningBorder: petrolLight.guidance,
    ring: petrolLight.primary,
    primaryTint: petrolLight.primaryTint, attention: petrolLight.accent, onAttention: petrolLight.onAccent,
    attentionTint: petrolLight.accentTint, successTint: petrolLight.successTint, separator: petrolLight.separator,
    chart: [
      { bar: "#C2185B", tint: "#FCE4EC", soft: "#F8BBD0", foreground: "#4A0A24" },
      { bar: "#B45309", tint: "#FEF3C7", soft: "#FCD34D", foreground: "#3B2200" },
      { bar: "#0F766E", tint: "#CCFBF1", soft: "#99F6E4", foreground: "#032F2B" },
      { bar: "#4338CA", tint: "#E0E7FF", soft: "#C7D2FE", foreground: "#1B1670" },
      { bar: "#7E22CE", tint: "#F3E8FF", soft: "#E9D5FF", foreground: "#3B0764" }
    ],
    chartPart2: { bar: "#475569", tint: "#F1F5F9", soft: "#E2E8F0", foreground: "#1E293B" },
    scrim: "rgba(15, 23, 42, 0.45)",
    shadow: "0 8px 24px rgba(15, 23, 42, 0.18)"
  },
  dark: {
    ...zincDark,
    // Derived dark mode: the card tone for cards and inputs on the dark canvas; no shadow.
    page: petrolDark.canvas, background: petrolDark.card, card: petrolDark.card, popover: petrolDark.card,
    foreground: petrolDark.text, cardForeground: petrolDark.text, popoverForeground: petrolDark.text,
    secondary: petrolDark.neutralFill, secondaryForeground: petrolDark.text, muted: petrolDark.neutralFill,
    accent: petrolDark.primaryTint, accentForeground: petrolDark.text, mutedForeground: petrolDark.secondaryText,
    border: petrolDark.separator, input: petrolDark.controlEdge,
    // Dark-mode buttons carry ink text.
    primary: petrolDark.primary, primaryForeground: petrolDark.onPrimary, primaryPressed: petrolDark.primaryPressed,
    // The error fill stays the light-mode red (light text 5.5:1); the dark error colour is for text only.
    destructive: petrolLight.error, destructiveForeground: petrolDark.text,
    destructiveText: petrolDark.error, destructiveSoft: petrolDark.errorTint, success: petrolDark.success,
    warningText: petrolDark.guidance, disabled: petrolDark.disabled,
    warning: petrolDark.accentTint, warningForeground: petrolDark.text, warningBorder: petrolDark.accent,
    ring: petrolDark.primary,
    primaryTint: petrolDark.primaryTint, attention: petrolDark.accent, onAttention: petrolDark.onAccent,
    attentionTint: petrolDark.accentTint, successTint: petrolDark.successTint, separator: petrolDark.separator,
    chart: [
      { bar: "#F48FB1", tint: "#3B1A27", soft: "#6A2540", foreground: "#FFE4EE" },
      { bar: "#FBBF24", tint: "#38280B", soft: "#6B4A0C", foreground: "#FFF3D1" },
      { bar: "#2DD4BF", tint: "#0E3330", soft: "#145C55", foreground: "#D9FFF8" },
      { bar: "#A5B4FC", tint: "#22264F", soft: "#3B418D", foreground: "#EEF0FF" },
      { bar: "#D8B4FE", tint: "#2E1A47", soft: "#5B2A8C", foreground: "#F7ECFF" }
    ],
    chartPart2: { bar: "#94A3B8", tint: "#1E2733", soft: "#334155", foreground: "#F1F5F9" },
    scrim: "rgba(0, 0, 0, 0.6)",
    shadow: "0 8px 24px rgba(0, 0, 0, 0.5)"
  }
  };
}

export const ui: Record<ColorMode, UiTokens> = petrolTokens(petrolHex("light"), petrolHex("dark"));
/** Settings > Display > High contrast: the same token names on the high-contrast Petrol palette. */
export const uiHighContrast: Record<ColorMode, UiTokens> = petrolTokens(petrolHex("light", true), petrolHex("dark", true));

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

/**
 * System fonts provide broad multi-script coverage; the web gets an explicit fallback stack. These are the Medium
 * sizes; screens read `useTheme().typography` (and `.fontSize`), which carry the Text size setting.
 */
export const typography = {
  largeTitle: { fontSize: fontSize.display, lineHeight: 34, fontWeight: "700" as const },
  title: { fontSize: fontSize.title, lineHeight: 32, fontWeight: "700" as const },
  headline: { fontSize: fontSize.headline, lineHeight: 26, fontWeight: "600" as const },
  /** Sheet titles and a screen's one name heading (Unlock, Set PIN): 20pt semibold, below the page title. */
  heading: { fontSize: fontSize.heading, lineHeight: 28, fontWeight: "600" as const },
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

/**
 * Control height 48 (fields and full-width buttons), 36 for compact controls inside a row (segmented, chips, small
 * buttons; their hit slop makes the 44 tap target), 44 minimum tap target, 12px gaps, 16px card padding.
 */
export const controls = {
  minHeight: 48,
  compactHeight: 36,
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
const paletteHighContrast: Record<ColorMode, Palette> = { light: paletteOf(uiHighContrast.light), dark: paletteOf(uiHighContrast.dark) };

export type ButtonVariant = "default" | "secondary" | "outline" | "ghost" | "destructive";
export type ButtonSize = "sm" | "default" | "icon";

/**
 * Fill, border and text colour of a button variant; shared by `Button` in src/ui.tsx and the DORIS kit.
 * Petrol: primary filled, secondary tint-filled with primary text (no outline inside a card), destructive red text.
 */
export const buttonTone = (t: UiTokens, variant: ButtonVariant) => ({
  default: { bg: t.primary, border: t.primary, fg: t.primaryForeground },
  secondary: { bg: t.primaryTint, border: t.primaryTint, fg: t.primary },
  outline: { bg: t.background, border: t.input, fg: t.foreground },
  ghost: { bg: "transparent", border: "transparent", fg: t.foreground },
  destructive: { bg: "transparent", border: "transparent", fg: t.destructiveText }
})[variant];

/** `fg` laid over `bg` at `alpha` (0..1), as hex: the colour a faded label draws. */
export function blendHex(fg: string, bg: string, alpha: number): string {
  const channel = (hex: string, at: number) => parseInt(hex.slice(at, at + 2), 16);
  const mix = (at: number) => Math.round(channel(fg, at) * alpha + channel(bg, at) * (1 - alpha)).toString(16).padStart(2, "0");
  return `#${mix(1)}${mix(3)}${mix(5)}`.toUpperCase();
}

const luminance = (hex: string) => {
  const linear = (at: number) => {
    const c = parseInt(hex.slice(at, at + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * linear(1) + 0.7152 * linear(3) + 0.0722 * linear(5);
};

/** WCAG contrast ratio of two hex colours. */
export function contrastRatio(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * A disabled filled button: the primary tint with the primary label faded toward it, never the canvas grey (which
 * read as a missing button). The fade starts at 60% and stops where the label would fall under 4.5:1.
 */
export const disabledButtonTone = (t: UiTokens) => {
  let alpha = 0.6;
  while (alpha < 1 && contrastRatio(blendHex(t.primary, t.primaryTint, alpha), t.primaryTint) < 4.5) alpha = Math.min(1, alpha + 0.05);
  return { bg: t.primaryTint, border: t.primaryTint, fg: blendHex(t.primary, t.primaryTint, alpha) };
};

/** Minimum button width (also chips): short labels such as "No" or "Add" never collapse into a circle. */
export const BUTTON_MIN_WIDTH = 72;
/** A switch's thumb: white in both modes and contrasts, on the primary (on) or border (off) track. */
export const SWITCH_THUMB = "#ffffff";

/** Settings > Display > Text size: the factor each choice puts on every text token. */
export const TEXT_SIZE_SCALE: Record<TextSizePreference, number> = { small: 0.9, medium: 1, large: 1.2 };
/** The largest text the app draws: the Text size choice times the phone's font size, capped (WCAG 1.4.4, 200%). */
export const MAX_TEXT_SCALE = 2;

/**
 * The factor the font tokens carry. React Native multiplies every font size and line height by the phone's font
 * scale itself, so the tokens carry the Text size choice divided back by whatever exceeds the 2.0 cap: on screen
 * the text is choice x phone scale, never more than 2.0x the Medium size. A missing or zero phone scale is 1.
 */
export function tokenTextScale(size: TextSizePreference, osFontScale: number): number {
  const os = osFontScale > 0 ? osFontScale : 1;
  return Math.min(TEXT_SIZE_SCALE[size] * os, MAX_TEXT_SCALE) / os;
}

export type Typography = Record<keyof typeof typography, { fontSize: number; lineHeight: number; fontWeight: NonNullable<TextStyle["fontWeight"]> }>;
export type FontSizes = Record<keyof typeof fontSize, number>;

const scaled = (value: number, factor: number) => Math.round(value * factor * 2) / 2;

/** The text tokens times `factor` (sizes and line heights, to the half point). */
export function scaleTypography(factor: number): { typography: Typography; fontSize: FontSizes } {
  const entries = Object.entries(typography).map(([name, style]) => [name, { ...style, fontSize: scaled(style.fontSize, factor), lineHeight: scaled(style.lineHeight, factor) }]);
  const sizes = Object.entries(fontSize).map(([name, size]) => [name, scaled(size, factor)]);
  return { typography: Object.fromEntries(entries) as Typography, fontSize: Object.fromEntries(sizes) as FontSizes };
}

export type Theme = {
  mode: ColorMode;
  /** Settings > Display > High contrast, after the phone's own contrast setting (src/themeColors.ts petrolHighContrast). */
  highContrast: boolean;
  /** The factor on the text tokens (tokenTextScale); sizes that must grow with the text (PIN digits) multiply by it. */
  textScale: number;
  /** Width of the focus ring on the field being typed in (and the web outline): thicker in high contrast. */
  focusWidth: number;
  colors: Palette;
  spacing: typeof spacing;
  typography: Typography;
  fontSize: FontSizes;
  radius: typeof radius;
  controls: typeof controls;
  ui: UiTokens;
};

const scaleCache = new Map<number, ReturnType<typeof scaleTypography>>();

export function getTheme(mode: ColorMode, options: { highContrast?: boolean; textScale?: number } = {}): Theme {
  const highContrast = options.highContrast ?? false;
  const textScale = options.textScale ?? 1;
  let text = scaleCache.get(textScale);
  if (!text) {
    text = scaleTypography(textScale);
    scaleCache.set(textScale, text);
  }
  return {
    mode, highContrast, textScale, focusWidth: highContrast ? 3 : 2,
    colors: (highContrast ? paletteHighContrast : palette)[mode], spacing, ...text, radius, controls,
    ui: (highContrast ? uiHighContrast : ui)[mode]
  };
}

/*
 * One shared preference store (theme, text size, high contrast, and the phone's own contrast setting). Every
 * useTheme() instance reads the same in-memory value synchronously, so a remount never repaints with another
 * scheme. Web primes from localStorage at module load (before first render); native renders the defaults until
 * its async reads land.
 */
type DisplayState = {
  theme: ThemePreference;
  textSize: TextSizePreference;
  highContrast: HighContrastPreference;
  /** The phone asks for more contrast (Android high-contrast text, iOS Increase Contrast, web prefers-contrast). */
  osHighContrast: boolean;
};
let stored: DisplayState = {
  theme: peekUiTheme() ?? "system",
  textSize: peekUiTextSize() ?? "medium",
  highContrast: peekUiHighContrast() ?? "system",
  osHighContrast: false
};
const storeListeners = new Set<() => void>();

function applyDisplay(patch: Partial<DisplayState>) {
  const next = { ...stored, ...patch };
  if ((Object.keys(next) as (keyof DisplayState)[]).every((key) => next[key] === stored[key])) return;
  stored = next;
  for (const listener of storeListeners) listener();
}

if (peekUiTheme() === null || peekUiTextSize() === null || peekUiHighContrast() === null) {
  // getUiPreference already lets a preference set while the read was in flight win.
  void Promise.all([getUiTheme(), getUiTextSize(), getUiHighContrast()])
    .then(([theme, textSize, highContrast]) => applyDisplay({ theme, textSize, highContrast }))
    .catch(() => undefined);
}
subscribeUiPreferences(() => {
  // Unknown (null) means keep the current value, e.g. a locale change before any theme read.
  const patch: Partial<DisplayState> = {};
  const theme = peekUiTheme();
  const textSize = peekUiTextSize();
  const highContrast = peekUiHighContrast();
  if (theme !== null) patch.theme = theme;
  if (textSize !== null) patch.textSize = textSize;
  if (highContrast !== null) patch.highContrast = highContrast;
  applyDisplay(patch);
});

/** The phone's own contrast request, read once and followed while the app runs. Missing APIs mean "no". */
function watchOsContrast() {
  if (Platform.OS === "web") {
    const query = typeof globalThis.matchMedia === "function" ? globalThis.matchMedia("(prefers-contrast: more)") : undefined;
    if (!query) return;
    applyDisplay({ osHighContrast: query.matches });
    query.addEventListener?.("change", (event) => applyDisplay({ osHighContrast: event.matches }));
    return;
  }
  const android = Platform.OS === "android";
  const read = android ? AccessibilityInfo.isHighTextContrastEnabled : AccessibilityInfo.isDarkerSystemColorsEnabled;
  if (typeof read !== "function") return;
  void read.call(AccessibilityInfo).then((on) => applyDisplay({ osHighContrast: Boolean(on) })).catch(() => undefined);
  const onChange = (on: boolean) => applyDisplay({ osHighContrast: Boolean(on) });
  if (typeof AccessibilityInfo.addEventListener !== "function") return;
  if (android) AccessibilityInfo.addEventListener("highTextContrastChanged", onChange);
  else AccessibilityInfo.addEventListener("darkerSystemColorsChanged", onChange);
}
watchOsContrast();

function subscribeStore(listener: () => void) {
  storeListeners.add(listener);
  return () => {
    storeListeners.delete(listener);
  };
}
const getStored = () => stored;

/** High contrast is on when chosen, or, until the user chooses, when the phone asks for more contrast. */
export const highContrastOn = (preference: HighContrastPreference, osHighContrast: boolean) =>
  preference === "system" ? osHighContrast : preference === "on";

/**
 * Theme hook. The stored preferences are UI-only and device-local: colour scheme (defaults to the platform's),
 * text size and high contrast. Hindi and other scripts continue to use the platform font.
 */
export function useTheme(): Theme & {
  preference: ThemePreference;
  setPreference: (preference: ThemePreference) => Promise<void>;
  textSize: TextSizePreference;
  setTextSize: (size: TextSizePreference) => Promise<void>;
  setHighContrast: (on: boolean) => Promise<void>;
} {
  const systemScheme = useColorScheme();
  const { fontScale } = useWindowDimensions();
  const state = useSyncExternalStore(subscribeStore, getStored, getStored);
  const mode: ColorMode = state.theme === "system" ? (systemScheme === "dark" ? "dark" : "light") : state.theme;
  const highContrast = highContrastOn(state.highContrast, state.osHighContrast);
  const textScale = tokenTextScale(state.textSize, fontScale);
  const theme = useMemo(() => getTheme(mode, { highContrast, textScale }), [mode, highContrast, textScale]);
  const updatePreference = useCallback(async (next: ThemePreference) => {
    applyDisplay({ theme: next });
    await setUiTheme(next);
  }, []);
  const updateTextSize = useCallback(async (next: TextSizePreference) => {
    applyDisplay({ textSize: next });
    await setUiTextSize(next);
  }, []);
  // The user's choice is stored explicitly, so it wins over the phone's setting from then on.
  const updateHighContrast = useCallback(async (on: boolean) => {
    const next = on ? "on" : "off";
    applyDisplay({ highContrast: next });
    await setUiHighContrast(next);
  }, []);
  return { ...theme, preference: state.theme, setPreference: updatePreference, textSize: state.textSize, setTextSize: updateTextSize, setHighContrast: updateHighContrast };
}

/** Test seam: reset the shared store to an explicit preference. */
export function __setThemePreferenceForTest(next: ThemePreference) {
  applyDisplay({ theme: next });
}

/** Test seam: set text size, high contrast or the phone's contrast setting in the shared store. */
export function __setDisplayForTest(patch: Partial<DisplayState>) {
  applyDisplay(patch);
}
