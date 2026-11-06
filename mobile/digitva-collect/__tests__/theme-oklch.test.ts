/** The Petrol colours are authored in OKLCH (src/themeColors.ts); each hex React Native draws must be that OKLCH value. */
import { petrol, petrolHighContrast } from "../src/themeColors";
import { ui } from "../src/theme";

const toGamma = (c: number) => (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);

/** CSS Color 4 OKLCH -> sRGB channels 0..255 (Björn Ottosson's matrices), clamped to the gamut. */
function oklchToRgb(text: string): number[] {
  const match = /^oklch\(([\d.]+)% ([\d.]+) ([\d.]+)\)$/.exec(text);
  if (!match) throw new Error(`not oklch: ${text}`);
  const [L, C, H] = [Number(match[1]) / 100, Number(match[2]), (Number(match[3]) * Math.PI) / 180];
  const a = C * Math.cos(H);
  const b = C * Math.sin(H);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.291485548 * b) ** 3;
  return [
    4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.707614701 * s
  ].map((c) => Math.round(Math.min(1, Math.max(0, toGamma(c))) * 255));
}

const hexRgb = (hex: string) => [1, 3, 5].map((at) => parseInt(hex.slice(at, at + 2), 16));

const rows = (["light", "dark"] as const).flatMap((mode) => [
  ...Object.entries(petrol[mode]).map(([name, value]) => [`${mode} ${name}`, value.oklch, value.hex] as const),
  ...Object.entries(petrolHighContrast[mode]).map(([name, value]) => [`${mode} high-contrast ${name}`, value.oklch, value.hex] as const)
]);

describe("petrol OKLCH source", () => {
  it("converts a known value exactly (the converter is not vacuous)", () => {
    expect(oklchToRgb("oklch(39.7% 0.059 228)")).toEqual(hexRgb("#1f4d60"));
    expect(oklchToRgb("oklch(100% 0 0)")).toEqual([255, 255, 255]);
    expect(() => oklchToRgb("#1f4d60")).toThrow();
  });

  it.each(rows)("%s: hex is its OKLCH within one step per channel", (_name, oklch, hex) => {
    expect(hex).toMatch(/^#[0-9a-f]{6}$/);
    const want = oklchToRgb(oklch);
    hexRgb(hex).forEach((channel, i) => expect(Math.abs(channel - want[i])).toBeLessThanOrEqual(1));
  });

  it("the ui tokens draw the README table values", () => {
    expect([ui.light.page, ui.light.card, ui.light.foreground, ui.light.mutedForeground]).toEqual(["#e8edf0", "#ffffff", "#1b232a", "#5c6872"]);
    expect([ui.light.primary, ui.light.primaryTint, ui.light.attention, ui.light.attentionTint]).toEqual(["#1f4d60", "#d2e5ec", "#d6a24a", "#fbe7c6"]);
    expect([ui.light.destructiveText, ui.light.destructiveSoft, ui.light.success, ui.light.successTint]).toEqual(["#b3261e", "#fbe9e7", "#1f7a4d", "#dcefe2"]);
    expect([ui.dark.page, ui.dark.card, ui.dark.foreground, ui.dark.mutedForeground]).toEqual(["#0f1418", "#1a2127", "#e8edf0", "#9aa6af"]);
    expect([ui.dark.primary, ui.dark.primaryTint, ui.dark.attention, ui.dark.attentionTint]).toEqual(["#6fb6d6", "#1f3a47", "#d6a24a", "#3a2f1c"]);
    expect([ui.dark.destructiveText, ui.dark.destructiveSoft, ui.dark.success, ui.dark.successTint]).toEqual(["#f08a80", "#3a1f1d", "#6cc796", "#1b3326"]);
    // The amber badge always carries ink text.
    expect(ui.light.onAttention).toBe("#1b232a");
    expect(ui.dark.onAttention).toBe("#1b232a");
  });
});
