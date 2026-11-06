// @vitest-environment jsdom

/**
 * Round-6 phone presentation: the form canvas, borderless section card, no error edge bar or draft caption on the
 * phone bar (`compactFooter`), full-contrast read-only values, tinted step buttons, muted hints, the left-aligned
 * stepper caption and the drawer's sheet title and 48dp rows.
 */
import React, { act, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { FormTheme, InstrumentDefinition } from "../src/index.js";
import { ENGLISH_UI_MESSAGES } from "../src/i18n.js";
import { createSectionNavigation } from "../src/ui/section-navigation.js";
import { defaultFormTheme, FormThemeContext, useFormTheme } from "../src/ui/theme.js";
import { applyNativeTheme } from "../src/ui/web-theme.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flatten = (style: unknown): Record<string, unknown> =>
  Array.isArray(style)
    ? Object.assign({}, ...style.map(flatten))
    : style && typeof style === "object"
      ? (style as Record<string, unknown>)
      : {};

vi.mock("react-native", () => {
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

const question = (name: string, extra: Record<string, unknown>) => ({
  name,
  sourceRow: 2,
  sourceType: "text",
  dataType: "string" as const,
  control: "text" as const,
  label: { en: name },
  hint: {},
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["a"],
  ...extra
});

const instrument = {
  id: "round6-test",
  title: "Round 6 test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "round6-test.json",
  sections: [{ name: "a", sourceRow: 1, order: 1, label: { en: "A" } }],
  questions: [
    question("needed", {
      order: 1,
      required: true,
      hint: { en: '<span style="color:red">Office use only</span>' }
    }),
    question("fixed", { order: 2, readOnly: true }),
    question("count", { order: 3, sourceType: "integer", dataType: "number", control: "integer" })
  ]
} as unknown as InstrumentDefinition;

const theme: FormTheme = {
  primary: "#1F4D60",
  onPrimary: "#FFFFFF",
  primarySoft: "#D2E5EC",
  accent: "#163847",
  surface: "#FFFFFF",
  surfaceAlt: "#E0E7EB",
  canvas: "#E8EDF0",
  border: "#D1D9DD",
  borderStrong: "#6B7C86",
  text: "#13232B",
  textMuted: "#5C6872",
  danger: "#B3261E",
  dangerSoft: "#FBE9E7",
  success: "#2E7D32",
  focus: "#1F4D60",
  scrim: "rgba(0, 0, 0, 0.45)",
  shadow: "#13232B"
};

afterEach(() => {
  document.body.replaceChildren();
});

const styleOf = (element: Element | null | undefined): Record<string, unknown> =>
  JSON.parse((element as HTMLElement | null)?.dataset.style ?? "{}") as Record<string, unknown>;

async function mount(compactFooter: boolean) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<WhoVaForm instrument={instrument} theme={theme} compactFooter={compactFooter} />);
  });
  const card = () => container.querySelector('[data-testid="question-card-needed"]');
  return { container, root, card };
}

async function pressNext(container: HTMLElement) {
  const next = Array.from(container.querySelectorAll<HTMLElement>("button")).find((button) =>
    /^(Next|Complete)$/.test(button.textContent ?? "")
  );
  expect(next).toBeDefined();
  await act(async () => next?.click());
  await vi.waitFor(() => expect(container.textContent).toContain("This question is required."));
}

describe("round-6 form on the phone bar", () => {
  it("lays the form on the host canvas with a borderless, shadowed section card and no draft caption", async () => {
    const { container, root, card } = await mount(true);
    const canvases = Array.from(container.querySelectorAll("[data-style]")).filter(
      (node) => styleOf(node)["backgroundColor"] === theme.canvas
    );
    expect(canvases.length).toBeGreaterThan(0);
    const cardStyle = styleOf(card()?.parentElement);
    expect(cardStyle["backgroundColor"]).toBe(theme.surface);
    expect(cardStyle["borderWidth"]).toBe(0);
    expect(cardStyle["shadowColor"]).toBe(theme.shadow);
    expect(container.textContent).not.toContain("Draft not saved yet");
    await act(async () => root.unmount());
  });

  it("keeps the card border and draft caption without the phone bar", async () => {
    const { container, root, card } = await mount(false);
    expect(styleOf(card()?.parentElement)["borderWidth"]).toBe(1);
    expect(container.textContent).toContain("Draft not saved yet");
    await act(async () => root.unmount());
  });

  it("marks a required error by tint and red message only on the phone bar, with the edge bar elsewhere", async () => {
    const phone = await mount(true);
    await pressNext(phone.container);
    expect(styleOf(phone.card())["borderLeftWidth"]).toBeUndefined();
    // The innermost node holding the message (its wrappers come first in document order).
    const message = Array.from(phone.container.querySelectorAll("div"))
      .filter((node) => node.textContent === "This question is required.")
      .at(-1);
    expect(styleOf(message)["color"]).toBe(theme.danger);
    await act(async () => phone.root.unmount());

    const wide = await mount(false);
    await pressNext(wide.container);
    expect(styleOf(wide.card())["borderLeftWidth"]).toBe(3);
    await act(async () => wide.root.unmount());
  });

  it("shows a read-only value at full contrast, tints the step buttons and keeps a coloured hint muted", async () => {
    const { container, root } = await mount(true);
    const fixed = container.querySelector('[data-testid="question-fixed"]');
    expect(fixed).not.toBeNull();
    expect(styleOf(fixed)["opacity"]).toBeUndefined();
    const decrease = container.querySelector('[data-testid="question-count-decrease"]');
    expect(decrease).not.toBeNull();
    expect(styleOf(decrease)["backgroundColor"]).toBe(theme.primarySoft);
    const hint = Array.from(container.querySelectorAll("div"))
      .filter((node) => node.textContent === "Office use only")
      .at(-1);
    expect(hint).toBeDefined();
    expect(styleOf(hint)["color"]).toBe(theme.textMuted);
    const colours = Array.from(container.querySelectorAll("[data-style]")).map(
      (node) => styleOf(node)["color"]
    );
    expect(colours).not.toContain("red");
    await act(async () => root.unmount());
  });
});

describe("round-6 section navigation", () => {
  /** What a themed native primitive draws: the style resolved against the host theme in context. */
  const useDrawn = (style: unknown) => JSON.stringify(flatten(applyNativeTheme(style, useFormTheme())));
  const View = React.forwardRef<HTMLDivElement, Record<string, unknown>>(
    ({ children, style, testID, onLayout }, ref) => {
      // The strip reports a phone width, so the caption offset under the current dot is real.
      useLayoutEffect(() => {
        (onLayout as ((event: unknown) => void) | undefined)?.({ nativeEvent: { layout: { width: 360 } } });
      }, [onLayout]);
      return (
        <div ref={ref} data-testid={testID as string} data-style={useDrawn(style)}>
          {children as React.ReactNode}
        </div>
      );
    }
  );
  const Text = ({ children, style }: Record<string, unknown>) => (
    <span data-style={useDrawn(style)}>{children as React.ReactNode}</span>
  );
  const Pressable = React.forwardRef<HTMLButtonElement, Record<string, unknown>>(
    ({ children, onPress, style, testID }, ref) => (
      <button
        ref={ref}
        type="button"
        data-testid={testID as string}
        data-style={useDrawn(style)}
        onClick={onPress as (() => void) | undefined}
      >
        {children as React.ReactNode}
      </button>
    )
  );
  const { SectionHeaderBar, SectionDrawer } = createSectionNavigation({
    View,
    Text,
    Pressable,
    ScrollView: View
  });
  const items = [
    { name: "one", label: "1. One", status: "complete" as const, active: false, depth: 0 },
    { name: "two", label: "2. Two", status: "complete" as const, active: false, depth: 0 },
    { name: "three", label: "3. Three", status: "started" as const, active: true, depth: 0 }
  ];

  async function render(element: React.ReactElement) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => root.render(element));
    return { container, root };
  }

  const header = (compact: boolean) => (
    <SectionHeaderBar
      compact={compact}
      current={3}
      items={items}
      messages={ENGLISH_UI_MESSAGES}
      moreToCome
      onOpen={() => undefined}
      onSelect={() => undefined}
      open={false}
      toggleRef={{ current: null }}
      total={3}
    />
  );

  it("keeps the caption at the left without the inline note on the phone bar", async () => {
    const lead = (container: HTMLElement) =>
      container.querySelector('[data-testid="section-drawer-toggle"]')?.firstElementChild;
    const wide = await render(header(false));
    expect(styleOf(lead(wide.container))["marginLeft"]).toBeGreaterThan(0);
    expect(wide.container.textContent).toContain(ENGLISH_UI_MESSAGES.moreSectionsNote);
    await act(async () => wide.root.unmount());

    const phone = await render(header(true));
    expect(styleOf(lead(phone.container))["marginLeft"]).toBe(0);
    expect(phone.container.textContent).toContain("Section 3 of 3");
    expect(phone.container.textContent).not.toContain(ENGLISH_UI_MESSAGES.moreSectionsNote);
    await act(async () => phone.root.unmount());
  });

  const drawer = (
    <SectionDrawer
      items={items}
      messages={ENGLISH_UI_MESSAGES}
      moreToCome={false}
      onClose={() => undefined}
      onSelect={() => undefined}
      open
      toggleRef={{ current: null }}
    />
  );
  const drawerTitle = (container: HTMLElement) =>
    Array.from(container.querySelectorAll("span")).find((node) => node.textContent === ENGLISH_UI_MESSAGES.sections);

  it("titles the drawer 20/600 in ink with an ink close glyph and 48dp rows under a host theme", async () => {
    const { container, root } = await render(
      <FormThemeContext.Provider value={defaultFormTheme}>{drawer}</FormThemeContext.Provider>
    );
    expect(styleOf(drawerTitle(container))).toMatchObject({
      color: defaultFormTheme.text,
      fontSize: 20,
      fontWeight: "600",
      lineHeight: 28
    });
    const rows = container.querySelectorAll('[data-testid="section-slider-item"]');
    expect(rows).toHaveLength(3);
    expect(styleOf(rows[0])["minHeight"]).toBe(48);
    await act(async () => root.unmount());
  });

  it("keeps the 16/700 drawer title and 40dp rows without a host theme", async () => {
    const { container, root } = await render(drawer);
    expect(drawerTitle(container)).toBeDefined();
    expect(styleOf(drawerTitle(container))).toMatchObject({ fontSize: 16, fontWeight: "700", lineHeight: 24 });
    const rows = container.querySelectorAll('[data-testid="section-slider-item"]');
    expect(rows).toHaveLength(3);
    expect(styleOf(rows[0])["minHeight"]).toBe(40);
    await act(async () => root.unmount());
  });
});
