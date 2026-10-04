// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const nativeState = vi.hoisted(() => ({
  modalOnRequestClose: undefined as (() => void) | undefined
}));

vi.mock("react-native", () => {
  const primitive = (tag: "div" | "button" | "input" | "img") =>
    React.forwardRef<HTMLElement, Record<string, unknown>>(
      (
        {
          accessibilityLabel,
          accessibilityRole,
          accessibilityState,
          children,
          onPress,
          style,
          testID,
          ...props
        },
        ref
      ) => {
        const state = accessibilityState as { disabled?: boolean; selected?: boolean } | undefined;
        const domProps = {
          "aria-label": accessibilityLabel,
          "aria-selected": state?.selected,
          "data-testid": testID,
          "data-style": style === undefined ? undefined : JSON.stringify(style),
          ...(accessibilityRole ? { role: accessibilityRole } : {}),
          ...(state?.disabled !== undefined ? { disabled: state.disabled } : {}),
          ...(onPress ? { onClick: onPress } : {})
        };
        const safeProps = Object.fromEntries(
          Object.entries(props).filter(([name]) =>
            ["disabled", "value", "placeholder", "src", "alt"].includes(name)
          )
        );
        return React.createElement(tag, { ...safeProps, ...domProps, ref }, children as React.ReactNode);
      }
    );

  const Modal = React.forwardRef<HTMLElement, Record<string, unknown>>(
    (
      {
        animationType: _animationType,
        children,
        onRequestClose,
        transparent: _transparent,
        visible: _visible,
        ...props
      },
      ref
    ) => {
      nativeState.modalOnRequestClose = onRequestClose as (() => void) | undefined;
      return React.createElement("div", { ...props, ref }, children as React.ReactNode);
    }
  );

  return {
    Image: primitive("img"),
    Modal,
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
  return {
    Circle: svgPrimitive("circle"),
    default: svgPrimitive("svg"),
    Path: svgPrimitive("path")
  };
});

import { WhoVaQuestionControls } from "../src/native.js";

const yearQuestion: InstrumentQuestion = {
  name: "birth_year",
  order: 1,
  sourceRow: 1,
  sourceType: "date",
  dataType: "date",
  control: "date",
  appearance: "year",
  label: { en: "Year of birth" },
  hint: {},
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["dates"]
};

afterEach(() => {
  nativeState.modalOnRequestClose = undefined;
  document.body.replaceChildren();
});

async function renderYear(value: string | undefined = undefined, readOnly = false) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const onAnswer = vi.fn();
  await act(async () => {
    root.render(
      <WhoVaQuestionControls.Date
        question={{ ...yearQuestion, readOnly }}
        value={value}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={onAnswer}
      />
    );
  });
  return { container, onAnswer, root };
}

function yearTrigger(container: HTMLElement) {
  return container.querySelector<HTMLButtonElement>('[data-testid="question-birth_year-year"]');
}

describe("native partial-date select", () => {
  it("bounds and scrolls a long year list while retaining an empty selected row", async () => {
    const { container, root } = await renderYear();

    await act(async () => yearTrigger(container)?.click());

    const surface = container.querySelector('[data-testid="question-birth_year-year-surface"]');
    const options = container.querySelector('[data-testid="question-birth_year-year-options"]');
    expect(surface?.getAttribute("data-style")).toContain('"maxHeight":"80%"');
    expect(options).not.toBeNull();
    expect(
      container.querySelectorAll('[data-testid^="question-birth_year-year-option-"]').length
    ).toBeGreaterThan(100);
    expect(
      container
        .querySelector('[data-testid="question-birth_year-year-option-empty"]')
        ?.getAttribute("aria-selected")
    ).toBe("true");

    await act(async () => root.unmount());
  });

  it("selects a year and closes the modal", async () => {
    const { container, onAnswer, root } = await renderYear();
    await act(async () => yearTrigger(container)?.click());

    const year = String(new Date().getFullYear());
    await act(async () =>
      container
        .querySelector<HTMLButtonElement>(`[data-testid="question-birth_year-year-option-${year}"]`)
        ?.click()
    );

    expect(onAnswer).toHaveBeenCalledWith(`${year}-01-01`);
    expect(container.querySelector('[data-testid="question-birth_year-year-options"]')).toBeNull();
    await act(async () => root.unmount());
  });

  it("closes on backdrop and Android back requests", async () => {
    const { container, root } = await renderYear();
    await act(async () => yearTrigger(container)?.click());
    await act(async () =>
      container.querySelector<HTMLButtonElement>('[data-testid="question-birth_year-year-backdrop"]')?.click()
    );
    expect(container.querySelector('[data-testid="question-birth_year-year-options"]')).toBeNull();

    await act(async () => yearTrigger(container)?.click());
    await act(async () => nativeState.modalOnRequestClose?.());
    expect(container.querySelector('[data-testid="question-birth_year-year-options"]')).toBeNull();
    await act(async () => root.unmount());
  });

  it("does not open when disabled", async () => {
    const { container, root } = await renderYear(undefined, true);
    const trigger = yearTrigger(container);
    expect(trigger?.disabled).toBe(true);

    await act(async () => trigger?.click());
    expect(container.querySelector('[data-testid="question-birth_year-year-options"]')).toBeNull();
    await act(async () => root.unmount());
  });
});
