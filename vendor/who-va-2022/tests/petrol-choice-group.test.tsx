// @vitest-environment jsdom

/**
 * Petrol theme (docs/design/collect-petrol-theme), drawn only when the host passes a `FormTheme` (DigitVA Collect):
 * a one-column choice list is one grouped card with inset hairlines, the selected row is a tint fill with a
 * semibold label, and a text field draws the focus ring only while focused. Without a host theme (the Flask web
 * component) none of these appear.
 */
import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";
import { questionControlStyles } from "../src/ui/question-control-support.js";
import { createWhoVaQuestionControls } from "../src/ui/question-controls.js";
import { defaultFormTheme, FormThemeContext, useFormTheme } from "../src/ui/theme.js";
import { applyNativeTheme } from "../src/ui/web-theme.js";

type HostProps = { children?: React.ReactNode; style?: unknown; testID?: string; [prop: string]: unknown };
const flatten = (style: unknown): Record<string, unknown> =>
  Array.isArray(style)
    ? Object.assign({}, ...style.map(flatten))
    : style && typeof style === "object"
      ? (style as Record<string, unknown>)
      : {};
/** Hosts that keep the flattened, theme-resolved style as JSON, so the test reads what React Native would draw. */
const host = (tag: string) =>
  function Host({ children, style, testID, onPress, onFocus, onBlur, accessibilityRole }: HostProps) {
    return React.createElement(
      tag,
      {
        "data-testid": testID,
        "data-style": JSON.stringify(flatten(applyNativeTheme(style, useFormTheme()))),
        "data-role": accessibilityRole,
        onClick: onPress,
        onFocus,
        onBlur
      },
      children
    );
  };

const Controls = createWhoVaQuestionControls({
  View: host("div"),
  Text: host("span"),
  TextInput: host("input"),
  Pressable: host("button")
} as never);

const choiceQuestion: InstrumentQuestion = {
  name: "Id10147",
  order: 1,
  sourceRow: 2,
  sourceType: "select_one yes_no",
  dataType: "string",
  control: "select_one",
  label: { en: "Did (s)he have a fever?" },
  hint: {},
  guidance: {},
  required: true,
  readOnly: false,
  constraintMessage: {},
  sectionPath: [],
  choices: [
    { value: "yes", label: { en: "Yes" } },
    { value: "no", label: { en: "No" } },
    { value: "dk", label: { en: "Doesn't know" } }
  ]
} as never;

/** Renders under the host theme (Petrol) unless `themed` is false (the Flask web component: no theme). */
async function render(element: React.ReactElement, themed = true) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  await act(async () =>
    root.render(
      themed ? <FormThemeContext.Provider value={defaultFormTheme}>{element}</FormThemeContext.Provider> : element
    )
  );
  return {
    container,
    done: () => {
      root.unmount();
      container.remove();
    }
  };
}
const styleOf = (node: Element | null | undefined) =>
  JSON.parse(node?.getAttribute("data-style") ?? "{}") as Record<string, unknown>;

describe("petrol choice list", () => {
  it("puts the rows in one grouped card split by inset hairlines, the selected row tinted and semibold", async () => {
    const { container, done } = await render(
      <Controls.SingleChoice
        question={choiceQuestion}
        value="yes"
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={vi.fn()}
      />
    );
    const group = container.querySelector('[data-testid="question-Id10147-choice-group"]');
    expect(group).not.toBeNull();
    expect(styleOf(group)).toMatchObject({ overflow: "hidden", borderRadius: 8 });
    const rows = group!.querySelectorAll("button");
    expect(rows).toHaveLength(3);
    // Two hairlines between three rows, none before the first.
    const separators = Array.from(group!.children).filter((child) => child.tagName === "DIV");
    expect(separators).toHaveLength(2);
    expect(group!.children[0]?.tagName).toBe("BUTTON");
    expect(styleOf(separators[0])).toMatchObject({ height: 1, marginLeft: 46 });
    for (const row of rows)
      expect(styleOf(row)).toMatchObject({ marginTop: 0, borderRadius: 0, borderWidth: 0 });
    const selected = container.querySelector('[data-testid="question-Id10147-choice-yes"]');
    expect(styleOf(selected).backgroundColor).toBe(defaultFormTheme.primarySoft);
    expect(styleOf(selected?.querySelector("span")).fontWeight).toBe("600");
    const other = container.querySelector('[data-testid="question-Id10147-choice-no"]');
    expect(styleOf(other?.querySelector("span")).fontWeight).toBeUndefined();
    done();
  });

  it("keeps the whole row as the target", async () => {
    const onAnswer = vi.fn();
    const { container, done } = await render(
      <Controls.SingleChoice
        question={choiceQuestion}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={onAnswer}
      />
    );
    await act(async () =>
      (container.querySelector('[data-testid="question-Id10147-choice-dk"]') as HTMLElement).click()
    );
    expect(onAnswer).toHaveBeenCalledWith("dk");
    done();
  });

  it("keeps separate edged rows and a regular selected label without a host theme", async () => {
    const { container, done } = await render(
      <Controls.SingleChoice
        question={choiceQuestion}
        value="yes"
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={vi.fn()}
      />,
      false
    );
    const selected = container.querySelector('[data-testid="question-Id10147-choice-yes"]');
    expect(selected).not.toBeNull();
    expect(container.querySelector('[data-testid="question-Id10147-choice-group"]')).toBeNull();
    expect(styleOf(selected)).toMatchObject({
      borderColor: defaultFormTheme.primary,
      borderWidth: 1,
      borderRadius: 8,
      marginTop: 8
    });
    expect(styleOf(selected?.querySelector("span")).fontWeight).toBeUndefined();
    done();
  });
});

describe("focus ring", () => {
  it("colours the field's edge only while it is focused", async () => {
    const textQuestion = {
      ...choiceQuestion,
      name: "Id10007",
      control: "text",
      sourceType: "text",
      choices: undefined
    } as never;
    const { container, done } = await render(
      <Controls.Text question={textQuestion} value="" data={{}} locale="en" issues={[]} onAnswer={vi.fn()} />
    );
    const input = container.querySelector('[data-testid="question-Id10007"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    const ring = flatten(questionControlStyles.inputFocused).borderColor;
    expect(styleOf(input).borderColor).not.toBe(ring);
    await act(async () => input.focus());
    expect(styleOf(container.querySelector('[data-testid="question-Id10007"]')).borderColor).toBe(ring);
    await act(async () => input.blur());
    expect(styleOf(container.querySelector('[data-testid="question-Id10007"]')).borderColor).not.toBe(ring);
    done();
  });

  it("keeps the strong control edge while focused without a host theme", async () => {
    const textQuestion = {
      ...choiceQuestion,
      name: "Id10007",
      control: "text",
      sourceType: "text",
      choices: undefined
    } as never;
    const { container, done } = await render(
      <Controls.Text question={textQuestion} value="" data={{}} locale="en" issues={[]} onAnswer={vi.fn()} />,
      false
    );
    const input = container.querySelector('[data-testid="question-Id10007"]') as HTMLInputElement;
    expect(input).not.toBeNull();
    await act(async () => input.focus());
    expect(styleOf(container.querySelector('[data-testid="question-Id10007"]'))).toMatchObject({
      borderColor: defaultFormTheme.borderStrong,
      borderWidth: 1
    });
    done();
  });
});
