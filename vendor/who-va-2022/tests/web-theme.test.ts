import { describe, expect, it } from "vitest";

import { defaultFormTheme } from "../src/ui/theme.js";
import { applyNativeTheme, applyWebTheme, withWebTheme } from "../src/ui/web-theme.js";

describe("explicit web theme bindings", () => {
  it("themes annotated properties without inspecting their literal values", () => {
    const style = withWebTheme(
      { color: "ordinary-value", borderRadius: 999, padding: 999 },
      { color: "ink", borderRadius: "controlRadius", padding: "formPadding" }
    );

    expect(applyWebTheme(style)).toEqual({
      color: "var(--who-2022-web-color-ink, #1f2937)",
      borderRadius: "var(--who-2022-web-radius-control, 8px)",
      paddingBlock:
        "var(--who-2022-web-form-padding-block, var(--who-2022-web-form-padding, clamp(1rem, 2.5vw, 1.5rem)))",
      paddingInline:
        "var(--who-2022-web-form-padding-inline, var(--who-2022-web-form-padding, clamp(1rem, 2.5vw, 1.5rem)))"
    });
  });

  it("does not theme an unannotated style that happens to contain old magic values", () => {
    const style = { color: "#142a24", borderRadius: 8, padding: 20, maxWidth: 760 };

    expect(applyWebTheme(style)).toBe(style);
  });

  it("resolves annotated styles nested in React Native style arrays", () => {
    const base = withWebTheme({ backgroundColor: "#ffffff" }, { backgroundColor: "surface" });
    const override = { opacity: 0.5 };

    expect(applyWebTheme([base, override])).toEqual([
      { backgroundColor: "var(--who-2022-web-color-surface, #ffffff)" },
      override
    ]);
  });

  it("takes colours from a passed form theme, on web and native, and layout tokens stay web-only", () => {
    const theme = { ...defaultFormTheme, primary: "#1D4ED8", onPrimary: "#FFFFFF" };
    const style = withWebTheme(
      { backgroundColor: "x", color: "y", borderRadius: 1 },
      { backgroundColor: "brand", borderRadius: "controlRadius" },
      { color: "onPrimary" }
    );

    expect(applyWebTheme(style, theme)).toMatchObject({
      backgroundColor: "#1D4ED8",
      color: "#FFFFFF",
      borderRadius: "var(--who-2022-web-radius-control, 8px)"
    });
    expect(applyNativeTheme(style, theme)).toEqual({
      backgroundColor: "#1D4ED8",
      color: "#FFFFFF",
      borderRadius: 1
    });
    expect(applyNativeTheme(style, undefined)).toBe(style);
  });
});
