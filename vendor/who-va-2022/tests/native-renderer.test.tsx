// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentDefinition } from "../src/index.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("react-native", () => {
  const primitive = (tag: "div" | "button" | "input" | "img") =>
    React.forwardRef<HTMLElement, Record<string, unknown>>(
      (
        {
          accessibilityLabel,
          accessibilityRole,
          accessibilityState,
          children,
          onChangeText,
          onPress,
          testID,
          ...props
        },
        ref
      ) => {
        const disabled = (accessibilityState as { disabled?: boolean } | undefined)?.disabled;
        const changeText = onChangeText as ((value: string) => void) | undefined;
        const domProps = {
          "aria-label": accessibilityLabel,
          "data-testid": testID,
          ...(accessibilityRole ? { role: accessibilityRole } : {}),
          ...(disabled !== undefined ? { disabled } : {}),
          ...(onPress ? { onClick: onPress } : {}),
          ...(changeText
            ? {
                onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
                  changeText(event.currentTarget.value)
              }
            : {})
        };
        const safeProps = Object.fromEntries(
          Object.entries(props).filter(([name]) => ["value", "placeholder", "src", "alt"].includes(name))
        );
        return React.createElement(tag, { ...safeProps, ...domProps, ref }, children as React.ReactNode);
      }
    );
  return {
    Image: primitive("img"),
    Pressable: primitive("button"),
    ScrollView: primitive("div"),
    Text: primitive("div"),
    TextInput: primitive("input"),
    View: primitive("div")
  };
});

vi.mock("react-native-svg", () => {
  const svgPrimitive = (tag: "circle" | "path" | "svg") =>
    React.forwardRef<SVGElement, Record<string, unknown>>(({ children, ...props }, ref) =>
      React.createElement(tag, { ...props, ref }, children as React.ReactNode)
    );
  return {
    Circle: svgPrimitive("circle"),
    default: svgPrimitive("svg"),
    Path: svgPrimitive("path")
  };
});

import { WhoVaForm } from "../src/native.js";

const nativeInstrument: InstrumentDefinition = {
  id: "native-renderer-test",
  title: "Native renderer test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "native-renderer-test.json",
  sections: [
    { name: "dates", sourceRow: 1, order: 1, label: { en: "Dates" } },
    { name: "details", sourceRow: 3, order: 2, label: { en: "Details" } }
  ],
  questions: [
    {
      name: "interview_date",
      order: 1,
      sourceRow: 2,
      sourceType: "date",
      dataType: "date",
      control: "date",
      appearance: "no-calendar",
      label: { en: "Interview date" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["dates"]
    },
    {
      name: "notes",
      order: 2,
      sourceRow: 4,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Notes" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["details"]
    }
  ]
};

afterEach(() => {
  document.body.replaceChildren();
});

function button(container: HTMLElement, label: string): HTMLButtonElement | undefined {
  return Array.from(container.querySelectorAll<HTMLButtonElement>("button")).find(
    (candidate) => candidate.textContent === label
  );
}

describe("native renderer integration", () => {
  it("mounts the native entry, navigates sections, and delegates controls to host services", async () => {
    const pickDate = vi.fn().mockResolvedValue("2026-07-18");
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    await act(async () => {
      root.render(<WhoVaForm instrument={nativeInstrument} platform={{ pickDate }} />);
    });

    expect(container.textContent).toContain("Section 1 of 2");
    expect(container.textContent).toContain("Dates");

    await act(async () => {
      container.querySelector<HTMLButtonElement>('[data-testid="question-interview_date"]')?.click();
    });
    expect(pickDate).toHaveBeenCalledWith(expect.objectContaining({ name: "interview_date" }), {}, undefined);
    expect(container.textContent).toContain("Jul-18-2026");

    await act(async () => {
      button(container, "Next")?.click();
    });
    expect(container.textContent).toContain("Section 2 of 2");
    expect(container.textContent).toContain("Details");
    expect(container.querySelector('[data-testid="question-notes"]')).not.toBeNull();

    await act(async () => root.unmount());
  });
});
