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
 * contrast and screen readers"): text, secondary text and primary at 7:1 or better on every background they sit
 * on, separators and field edges at 3:1, and a stronger canvas/card step. Same names as `petrol`; the contrast
 * test (__tests__/ui-token-contrast.test.ts) holds each pair to its ratio.
 */
export const petrolHighContrast: Record<"light" | "dark", Record<PetrolName, OklchColour>> = {
  light: {
    canvas: c("oklch(88% 0.012 234)", "#d0d9de"),
    card: c("oklch(100% 0 0)", "#ffffff"),
    text: c("oklch(16% 0.015 245)", "#080e13"),
    secondaryText: c("oklch(32% 0.02 243)", "#2a343c"),
    primary: c("oklch(30% 0.06 228)", "#003345"),
    primaryPressed: c("oklch(24% 0.05 228)", "#002332"),
    onPrimary: c("oklch(100% 0 0)", "#ffffff"),
    primaryTint: c("oklch(93% 0.025 222)", "#d7ecf4"),
    accent: c("oklch(74.4% 0.121 78)", "#d6a24a"),
    onAccent: c("oklch(16% 0.015 245)", "#080e13"),
    accentTint: c("oklch(94% 0.05 80)", "#fde8c6"),
    error: c("oklch(38% 0.14 29)", "#7c130d"),
    errorTint: c("oklch(95% 0.02 25)", "#fceae8"),
    success: c("oklch(38% 0.09 157)", "#01502e"),
    successTint: c("oklch(95% 0.027 156)", "#e1f4e7"),
    neutralFill: c("oklch(94% 0.008 228)", "#e6ecef"),
    separator: c("oklch(56% 0.02 228)", "#69777e"),
    controlEdge: c("oklch(45% 0.02 228)", "#4a585e"),
    disabled: c("oklch(55% 0.015 228)", "#697379"),
    guidance: c("oklch(36% 0.08 70)", "#573400")
  },
  dark: {
    canvas: c("oklch(8% 0.005 242)", "#010202"),
    card: c("oklch(25% 0.015 244)", "#1c2328"),
    text: c("oklch(100% 0 0)", "#ffffff"),
    secondaryText: c("oklch(90% 0.012 240)", "#d7dfe5"),
    primary: c("oklch(86% 0.07 229)", "#a1dbf6"),
    primaryPressed: c("oklch(92% 0.05 228)", "#c3ecff"),
    onPrimary: c("oklch(8% 0.005 242)", "#010202"),
    primaryTint: c("oklch(30% 0.045 230)", "#123240"),
    accent: c("oklch(80% 0.12 78)", "#e8b45e"),
    onAccent: c("oklch(16% 0.015 245)", "#080e13"),
    accentTint: c("oklch(30% 0.04 81)", "#382c15"),
    error: c("oklch(85% 0.08 26)", "#febab3"),
    errorTint: c("oklch(28% 0.05 25)", "#3e1e1c"),
    success: c("oklch(86% 0.09 159)", "#9de4bc"),
    successTint: c("oklch(28% 0.04 159)", "#162f22"),
    neutralFill: c("oklch(28% 0.012 228)", "#232a2e"),
    separator: c("oklch(58% 0.02 228)", "#6f7d84"),
    controlEdge: c("oklch(68% 0.02 228)", "#8c9ba2"),
    disabled: c("oklch(62% 0.015 228)", "#7d888d"),
    guidance: c("oklch(88% 0.09 80)", "#f7d293")
  }
};

/** The hex of every petrol colour of one mode (high contrast when `highContrast`), for the `ui` tokens. */
export function petrolHex(mode: "light" | "dark", highContrast = false): Record<PetrolName, string> {
  const source = highContrast ? petrolHighContrast[mode] : petrol[mode];
  return Object.fromEntries(Object.entries(source).map(([name, value]) => [name, value.hex])) as Record<PetrolName, string>;
}
