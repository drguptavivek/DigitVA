/** Every text/background pair the form engine draws from the app's form theme keeps >= 4.5:1 (control edges >= 3:1), light and dark. */
import { getTheme, type ColorMode } from "../src/theme";
import { whoFormTheme } from "../src/whoWebTheme";

const channel = (hex: string, at: number) => {
  const value = parseInt(hex.slice(at, at + 2), 16) / 255;
  return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
};
const luminance = (hex: string) => 0.2126 * channel(hex, 1) + 0.7152 * channel(hex, 3) + 0.0722 * channel(hex, 5);
const contrast = (a: string, b: string) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe.each(["light", "dark"] as ColorMode[])("%s form theme", (mode) => {
  const f = whoFormTheme(getTheme(mode));
  const text: ReadonlyArray<[string, string, string]> = [
    ["text on card", f.text, f.surface],
    ["text on page", f.text, f.surfaceAlt],
    ["text on selected row", f.text, f.primarySoft],
    ["muted text on card", f.textMuted, f.surface],
    ["muted text on page", f.textMuted, f.surfaceAlt],
    ["guidance text on card", f.accent, f.surface],
    ["guidance text on page", f.accent, f.surfaceAlt],
    ["guidance tag on its fill", f.accent, f.primarySoft],
    ["heading and secondary button on card", f.primary, f.surface],
    ["heading on page", f.primary, f.surfaceAlt],
    ["secondary button label", f.primary, f.primarySoft],
    ["Next and Complete label", f.onPrimary, f.primary],
    ["answered check on its badge", f.onPrimary, f.success],
    ["destructive fill label", f.onPrimary, f.danger],
    ["error text on card", f.danger, f.surface],
    ["error text on page", f.danger, f.surfaceAlt],
    ["error text on its tint", f.danger, f.dangerSoft]
  ];
  it.each(text)("%s is at least 4.5:1", (_name, fg, bg) => {
    expect(contrast(fg, bg)).toBeGreaterThanOrEqual(4.5);
  });

  it("keeps control edges and selected-row edges at 3:1 on the card", () => {
    expect(contrast(f.borderStrong, f.surface)).toBeGreaterThanOrEqual(3);
    expect(contrast(f.primary, f.surface)).toBeGreaterThanOrEqual(3);
  });
});
