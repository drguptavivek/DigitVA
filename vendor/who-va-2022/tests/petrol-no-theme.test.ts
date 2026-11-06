/**
 * The Petrol look is drawn only under a host `FormTheme` (DigitVA Collect). Without one (the Flask web component,
 * any default consumer) the touched control styles stay exactly as before Petrol: the same literals and the same
 * web tokens, so the CSS-variable path renders the old edges, widths and type.
 */
import { describe, expect, it } from "vitest";

import { questionControlStyles as Q } from "../src/ui/question-control-support.js";
import { navStyles as N } from "../src/ui/section-navigation.js";
import { defaultFormTheme as T } from "../src/ui/theme.js";
import { applyNativeTheme, applyWebTheme, withWebTheme } from "../src/ui/web-theme.js";

/** The pre-Petrol styles (git HEAD before the Petrol restyle), literals and web bindings. */
const before = {
  input: withWebTheme(
    {
      borderWidth: 1,
      borderColor: T.borderStrong,
      borderRadius: 8,
      minHeight: 44,
      paddingHorizontal: 12,
      paddingVertical: 9,
      color: T.text,
      backgroundColor: T.surface
    },
    { borderColor: "controlBorder", borderRadius: "controlRadius", color: "ink", backgroundColor: "surface" }
  ),
  inputError: withWebTheme(
    { borderColor: T.danger, backgroundColor: T.dangerSoft },
    { borderColor: "danger", backgroundColor: "dangerSoft" }
  ),
  choice: withWebTheme(
    {
      alignItems: "flex-start",
      borderWidth: 1,
      borderColor: T.borderStrong,
      borderRadius: 8,
      columnGap: 12,
      flexDirection: "row",
      minHeight: 48,
      paddingHorizontal: 12,
      paddingVertical: 11,
      marginTop: 8,
      backgroundColor: T.surface
    },
    { borderColor: "controlBorder", borderRadius: "controlRadius", backgroundColor: "surface" }
  ),
  choiceSelected: withWebTheme(
    { borderColor: T.primary, backgroundColor: T.primarySoft },
    { borderColor: "brand", backgroundColor: "brandSoft" }
  ),
  choiceEnglish: withWebTheme(
    { color: T.textMuted, fontSize: 13, fontStyle: "italic", lineHeight: 19 },
    { color: "muted" }
  ),
  stepButton: withWebTheme(
    {
      alignItems: "center",
      backgroundColor: T.border,
      borderRadius: 8,
      height: 44,
      justifyContent: "center",
      width: 44
    },
    { backgroundColor: "border", borderRadius: "controlRadius" }
  ),
  dateField: withWebTheme(
    {
      alignItems: "center",
      backgroundColor: T.surface,
      borderColor: T.borderStrong,
      borderRadius: 8,
      borderWidth: 1,
      flexDirection: "row",
      minHeight: 44,
      paddingHorizontal: 4
    },
    { backgroundColor: "surface", borderColor: "controlBorder", borderRadius: "controlRadius" }
  ),
  datePart: withWebTheme(
    { borderWidth: 0, color: T.text, fontSize: 16, minHeight: 40, paddingHorizontal: 6, textAlign: "center" },
    { color: "ink" }
  ),
  panelTitle: withWebTheme(
    { color: T.text, fontSize: 16, fontWeight: "700", lineHeight: 24 },
    { color: "brandDeep" }
  ),
  closeGlyph: withWebTheme({ color: T.text, fontSize: 18, lineHeight: 22 }, { color: "brandDeep" })
};

const current: Record<keyof typeof before, object> = {
  input: Q.input,
  inputError: Q.inputError,
  choice: Q.choice,
  choiceSelected: Q.choiceSelected,
  choiceEnglish: Q.choiceEnglish,
  stepButton: Q.stepButton,
  dateField: Q.dateField,
  datePart: Q.datePart,
  panelTitle: N.panelTitle,
  closeGlyph: N.closeGlyph
};

describe("no host theme: the pre-Petrol controls", () => {
  for (const name of Object.keys(before) as (keyof typeof before)[]) {
    it(`${name} keeps its literals and web tokens`, () => {
      expect(current[name]).toEqual(before[name]);
      expect(applyWebTheme(current[name])).toEqual(applyWebTheme(before[name]));
      expect(applyNativeTheme(current[name], undefined)).toEqual(before[name]);
    });
  }

  it("adds nothing for the Petrol-only selected weight and drawer row height", () => {
    expect(applyWebTheme(Q.choiceTextSelected)).toEqual({});
    expect(applyNativeTheme(N.stepRoomy, undefined)).toEqual({});
  });

  it("keeps the strong control edge on the web input (the 3:1 edge, not the hairline)", () => {
    expect(applyWebTheme(Q.input)).toMatchObject({
      borderWidth: 1,
      borderColor: expect.stringContaining("--who-2022-web-color-control-border")
    });
  });
});

describe("host theme: the Petrol controls", () => {
  const theme = {
    ...T,
    border: "#e1e6e4",
    primarySoft: "#e4f1ee",
    dangerSoft: "#fbe9e9",
    surface: "#fefefe"
  };

  it("draws the hairline 2px input edge, tint-only error and selection, and the 20/600 ink drawer title", () => {
    for (const apply of [applyWebTheme, applyNativeTheme] as const) {
      expect(apply(Q.input, theme)).toMatchObject({ borderWidth: 2, borderColor: theme.border });
      expect(apply(Q.inputError, theme)).toMatchObject({
        borderColor: theme.dangerSoft,
        backgroundColor: theme.dangerSoft
      });
      expect(apply(Q.choice, theme)).toMatchObject({ borderColor: theme.surface });
      expect(apply(Q.choiceSelected, theme)).toMatchObject({ borderColor: theme.primarySoft });
      expect(apply(Q.choiceEnglish, theme)).toMatchObject({
        color: theme.text,
        fontSize: 16,
        fontStyle: "normal",
        fontWeight: "400"
      });
      expect(apply(Q.choiceTextSelected, theme)).toEqual({ fontWeight: "600" });
      expect(apply(Q.stepButton, theme)).toMatchObject({ backgroundColor: theme.primarySoft });
      expect(apply(Q.dateField, theme)).toMatchObject({ borderColor: theme.border });
      expect(apply(N.panelTitle, theme)).toMatchObject({
        color: theme.text,
        fontSize: 20,
        fontWeight: "600"
      });
      expect(apply(N.closeGlyph, theme)).toMatchObject({ color: theme.text });
      expect(apply(N.stepRoomy, theme)).toEqual({ minHeight: 48 });
    }
  });
});
