import { getTheme } from "../src/theme";
import { choiceColumnsFor, whoWebThemeVars } from "../src/whoWebTheme";

describe("WHO web theme variables", () => {
  it("maps the light and dark palettes to different choice-row surfaces and ink", () => {
    const light = whoWebThemeVars(getTheme("light"));
    const dark = whoWebThemeVars(getTheme("dark"));
    expect(light["--who-2022-web-color-surface"]).toBe(getTheme("light").ui.background);
    expect(dark["--who-2022-web-color-surface"]).toBe(getTheme("dark").ui.background);
    expect(dark["--who-2022-web-color-ink"]).toBe(getTheme("dark").ui.foreground);
    expect(dark["--who-2022-web-color-surface"]).not.toBe(light["--who-2022-web-color-surface"]);
    expect(dark["--who-2022-web-color-control-border"]).toBe(getTheme("dark").ui.input);
    // The choice-row radius is the shared control radius, so DORIS rows (uiRadius.md) and WHO rows match.
    expect(light["--who-2022-web-radius-control"]).toBe("6px");
  });
});

describe("choiceColumnsFor", () => {
  const short = ["< 3 sentences", "Absent", "Present"];
  const long = ["A label that is clearly longer than eighteen characters"];
  it("uses 2 columns on phones and 3 elsewhere for short labels", () => {
    expect(choiceColumnsFor(375, short)).toBe(2);
    expect(choiceColumnsFor(700, short)).toBe(3);
    expect(choiceColumnsFor(1200, short)).toBe(3);
  });
  it("keeps the width rule when any label is long", () => {
    expect(choiceColumnsFor(375, long)).toBe(1);
    expect(choiceColumnsFor(700, long)).toBe(2);
    expect(choiceColumnsFor(1200, long)).toBe(3);
  });
});
