/**
 * Petrol theme colours (docs/design/collect-petrol-theme/README.md, owner decision 2026-11-05).
 *
 * OKLCH is the source of truth: change the `oklch` value, then the `hex` beside it. React Native draws the hex;
 * __tests__/theme-oklch.test.ts converts every OKLCH value to sRGB and fails when its hex is more than one step
 * off in any channel. Tones the README table does not list (pressed, separator, control edge, neutral fill,
 * disabled, guidance text) are derived on the petrol hue, 228.
 */
export type OklchColour = { oklch: string; hex: string };

const c = (oklch: string, hex: string): OklchColour => ({ oklch, hex });

export const petrol = {
  light: {
    canvas: c("oklch(94.3% 0.007 234)", "#e8edf0"),
    card: c("oklch(100% 0 0)", "#ffffff"),
    text: c("oklch(25.1% 0.018 245)", "#1b232a"),
    secondaryText: c("oklch(51.1% 0.022 243)", "#5c6872"),
    primary: c("oklch(39.7% 0.059 228)", "#1f4d60"),
    primaryPressed: c("oklch(33% 0.055 228)", "#0f3b4c"),
    onPrimary: c("oklch(100% 0 0)", "#ffffff"),
    primaryTint: c("oklch(91% 0.022 222)", "#d2e5ec"),
    accent: c("oklch(74.4% 0.121 78)", "#d6a24a"),
    onAccent: c("oklch(25.1% 0.018 245)", "#1b232a"),
    accentTint: c("oklch(93.6% 0.048 80)", "#fbe7c6"),
    error: c("oklch(50.1% 0.178 29)", "#b3261e"),
    errorTint: c("oklch(94.8% 0.02 25)", "#fbe9e7"),
    success: c("oklch(51.5% 0.11 157)", "#1f7a4d"),
    successTint: c("oklch(93.4% 0.027 156)", "#dcefe2"),
    // Derived.
    neutralFill: c("oklch(92.5% 0.009 228)", "#e0e7eb"),
    separator: c("oklch(88% 0.01 228)", "#d1d9dd"),
    controlEdge: c("oklch(56% 0.02 228)", "#69777e"),
    disabled: c("oklch(65% 0.015 228)", "#869196"),
    guidance: c("oklch(48% 0.09 70)", "#7e541b")
  },
  dark: {
    canvas: c("oklch(18.8% 0.011 242)", "#0f1418"),
    card: c("oklch(24.3% 0.015 244)", "#1a2127"),
    text: c("oklch(94.3% 0.007 234)", "#e8edf0"),
    secondaryText: c("oklch(71.8% 0.019 240)", "#9aa6af"),
    primary: c("oklch(74.1% 0.085 229)", "#6fb6d6"),
    primaryPressed: c("oklch(80% 0.08 228)", "#85c8e6"),
    onPrimary: c("oklch(18.8% 0.011 242)", "#0f1418"),
    primaryTint: c("oklch(33.3% 0.04 230)", "#1f3a47"),
    accent: c("oklch(74.4% 0.121 78)", "#d6a24a"),
    onAccent: c("oklch(25.1% 0.018 245)", "#1b232a"),
    accentTint: c("oklch(31.2% 0.035 81)", "#3a2f1c"),
    error: c("oklch(74% 0.126 26)", "#f08a80"),
    errorTint: c("oklch(27.5% 0.043 25)", "#3a1f1d"),
    success: c("oklch(76% 0.114 159)", "#6cc796"),
    successTint: c("oklch(29.7% 0.039 159)", "#1b3326"),
    // Derived.
    neutralFill: c("oklch(28% 0.012 228)", "#232a2e"),
    separator: c("oklch(32% 0.012 228)", "#2d3438"),
    controlEdge: c("oklch(62% 0.02 228)", "#7a8990"),
    disabled: c("oklch(55% 0.015 228)", "#697379"),
    guidance: c("oklch(84% 0.1 80)", "#edc47d")
  }
} as const;

export type PetrolName = keyof typeof petrol.light;

/**
 * The high-contrast palette (Settings > Display > High contrast, docs/policy/expo-client.md "Text size, high
 * contrast and screen readers"; owner decision 2026-11-17): neutral greys with no petrol hue (OKLCH chroma 0). By
 * day dark grey text and buttons on an almost-white page; by night almost-white text and buttons on a dark grey
 * page. Only meaning keeps colour: error red and success green. Same names as `petrol`; the contrast test
 * (__tests__/ui-token-contrast.test.ts) holds text and primary to 7:1, separators and field edges to 3:1, and a
 * stronger canvas/card step than the normal palette.
 */
export const petrolHighContrast: Record<"light" | "dark", Record<PetrolName, OklchColour>> = {
  light: {
    canvas: c("oklch(93% 0 0)", "#e8e8e8"),
    card: c("oklch(100% 0 0)", "#ffffff"),
    text: c("oklch(22% 0 0)", "#1b1b1b"),
    secondaryText: c("oklch(35% 0 0)", "#3a3a3a"),
    primary: c("oklch(25% 0 0)", "#222222"),
    primaryPressed: c("oklch(18% 0 0)", "#121212"),
    onPrimary: c("oklch(100% 0 0)", "#ffffff"),
    primaryTint: c("oklch(88% 0 0)", "#d7d7d7"),
    accent: c("oklch(75% 0 0)", "#aeaeae"),
    onAccent: c("oklch(22% 0 0)", "#1b1b1b"),
    accentTint: c("oklch(94% 0 0)", "#ebebeb"),
    error: c("oklch(38% 0.14 29)", "#7c130d"),
    errorTint: c("oklch(95% 0.02 25)", "#fceae8"),
    success: c("oklch(38% 0.09 157)", "#01502e"),
    successTint: c("oklch(95% 0.027 156)", "#e1f4e7"),
    neutralFill: c("oklch(90% 0 0)", "#dedede"),
    separator: c("oklch(56% 0 0)", "#747474"),
    controlEdge: c("oklch(50% 0 0)", "#636363"),
    disabled: c("oklch(58% 0 0)", "#7a7a7a"),
    guidance: c("oklch(35% 0 0)", "#3a3a3a")
  },
  dark: {
    canvas: c("oklch(20% 0 0)", "#161616"),
    card: c("oklch(28% 0 0)", "#292929"),
    text: c("oklch(97% 0 0)", "#f5f5f5"),
    secondaryText: c("oklch(85% 0 0)", "#cecece"),
    primary: c("oklch(93% 0 0)", "#e8e8e8"),
    primaryPressed: c("oklch(100% 0 0)", "#ffffff"),
    onPrimary: c("oklch(20% 0 0)", "#161616"),
    primaryTint: c("oklch(33% 0 0)", "#353535"),
    accent: c("oklch(75% 0 0)", "#aeaeae"),
    onAccent: c("oklch(20% 0 0)", "#161616"),
    accentTint: c("oklch(30% 0 0)", "#2e2e2e"),
    error: c("oklch(85% 0.08 26)", "#febab3"),
    errorTint: c("oklch(28% 0.05 25)", "#3e1e1c"),
    success: c("oklch(86% 0.09 159)", "#9de4bc"),
    successTint: c("oklch(28% 0.04 159)", "#162f22"),
    neutralFill: c("oklch(31% 0 0)", "#303030"),
    separator: c("oklch(58% 0 0)", "#7a7a7a"),
    controlEdge: c("oklch(64% 0 0)", "#8c8c8c"),
    disabled: c("oklch(55% 0 0)", "#717171"),
    guidance: c("oklch(88% 0 0)", "#d7d7d7")
  }
};

/** The hex of every petrol colour of one mode (high contrast when `highContrast`), for the `ui` tokens. */
export function petrolHex(mode: "light" | "dark", highContrast = false): Record<PetrolName, string> {
  const source = highContrast ? petrolHighContrast[mode] : petrol[mode];
  return Object.fromEntries(Object.entries(source).map(([name, value]) => [name, value.hex])) as Record<PetrolName, string>;
}
