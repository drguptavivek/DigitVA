// @vitest-environment jsdom

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { defaultFormTheme, type FormTheme, type InstrumentDefinition } from "../src/index.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("react-native", () => {
  const flatten = (style: unknown): Record<string, unknown> =>
    Array.isArray(style)
      ? Object.assign({}, ...style.map(flatten))
      : style && typeof style === "object"
        ? (style as Record<string, unknown>)
        : {};
  const primitive = (tag: "div" | "button" | "input" | "img") =>
    React.forwardRef<HTMLElement, Record<string, unknown>>(({ children, onPress, style, testID }, ref) =>
      React.createElement(
        tag,
        {
          ref,
          "data-testid": testID,
          "data-style": JSON.stringify(flatten(style)),
          ...(onPress ? { onClick: onPress } : {})
        },
        children as React.ReactNode
      )
    );
  return {
    Image: primitive("img"),
    Modal: primitive("div"),
    Pressable: primitive("button"),
    ScrollView: primitive("div"),
    Text: primitive("div"),
    TextInput: primitive("input"),
    View: primitive("div"),
    useColorScheme: () => "light"
  };
});

vi.mock("react-native-svg", () => {
  const svgPrimitive = (tag: "circle" | "path" | "svg") =>
    React.forwardRef<SVGElement, Record<string, unknown>>(({ children, ...props }, ref) =>
      React.createElement(tag, { ...props, ref }, children as React.ReactNode)
    );
  return { Circle: svgPrimitive("circle"), default: svgPrimitive("svg"), Path: svgPrimitive("path") };
});

import { WhoVaForm } from "../src/native.js";

const instrument: InstrumentDefinition = {
  id: "form-theme-test",
  title: "Form theme test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "form-theme-test.json",
  sections: [
    { name: "a", sourceRow: 1, order: 1, label: { en: "A" } },
    { name: "b", sourceRow: 3, order: 2, label: { en: "B" } }
  ],
  questions: [
    ["q1", "a"],
    ["q2", "b"]
  ].map(([name, section], index) => ({
    name: name!,
    order: index + 1,
    sourceRow: index + 2,
    sourceType: "text",
    dataType: "string" as const,
    control: "text" as const,
    label: { en: name! },
    hint: {},
    guidance: {},
    required: false,
    readOnly: false,
    constraintMessage: {},
    sectionPath: [section!]
  }))
};

const appTheme: FormTheme = {
  primary: "#1D4ED8",
  onPrimary: "#FFFFFF",
  primarySoft: "#E8F0FF",
  accent: "#1E40AF",
  surface: "#FFFFFF",
  surfaceAlt: "#EEF3F8",
  border: "#CBD5E1",
  borderStrong: "#6B7C93",
  text: "#09090B",
  textMuted: "#53657A",
  danger: "#B42318",
  dangerSoft: "#FDECEC",
  success: "#1F7A4D",
  focus: "#2563EB",
  scrim: "rgba(0, 0, 0, 0.5)"
};

afterEach(() => {
  document.body.replaceChildren();
});

async function nextButtonStyle(theme?: FormTheme): Promise<Record<string, unknown>> {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<WhoVaForm instrument={instrument} {...(theme ? { theme } : {})} />);
  });
  const next = Array.from(container.querySelectorAll<HTMLElement>("button")).find(
    (candidate) => candidate.textContent === "Next"
  );
  const style = JSON.parse(next?.dataset.style ?? "null") as Record<string, unknown>;
  await act(async () => root.unmount());
  return style;
}

describe("form theme", () => {
  it("fills the Next button with the passed primary and keeps the engine palette without a theme", async () => {
    expect((await nextButtonStyle(appTheme))["backgroundColor"]).toBe(appTheme.primary);
    expect((await nextButtonStyle())["backgroundColor"]).toBe(defaultFormTheme.primary);
  });

  it("has no colour literal in the engine UI outside theme.ts", () => {
    const src = join(import.meta.dirname, "..", "src");
    const files = [
      ...readdirSync(join(src, "ui")).map((name) => join(src, "ui", name)),
      join(src, "web.tsx"),
      join(src, "native.tsx"),
      join(src, "web-component.tsx")
    ].filter((file) => /\.tsx?$/.test(file) && !file.endsWith("/ui/theme.ts"));
    const offenders = files.flatMap((file) =>
      readFileSync(file, "utf8")
        .split("\n")
        .map((line, index) => ({ file, line, number: index + 1 }))
        .filter(({ line }) => !/^\s*(\*|\/\/|\/\*)/.test(line) && /"#[0-9a-f]{3,8}"|rgba?\(/i.test(line))
        .map(({ file: name, number }) => `${name}:${number}`)
    );
    expect(offenders).toEqual([]);
  });
});
