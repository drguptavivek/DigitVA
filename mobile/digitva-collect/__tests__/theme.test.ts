import { getTheme, palette, spacing, typography } from "../src/theme";

describe("shared theme", () => {
  it("keeps spacing on the four point grid and readable body text", () => {
    expect(Object.values(spacing).every((value) => value % 4 === 0)).toBe(true);
    expect(typography.body.fontSize).toBeGreaterThanOrEqual(16);
    expect(typography.body.fontSize).toBeLessThanOrEqual(17);
  });

  it("provides distinct semantic light and dark palettes", () => {
    expect(palette.light.accent).toBe("#1D4ED8");
    expect(palette.dark.accent).not.toBe(palette.light.accent);
    expect(getTheme("dark").colors.background).toBe(palette.dark.background);
    expect(getTheme("light").controls.minTouchTarget).toBe(48);
  });
});
