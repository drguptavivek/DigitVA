// @vitest-environment jsdom

import React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { WhoVaForm } from "../src/web.js";
import type { InstrumentDefinition } from "../src/index.js";
import hindi from "../src/languages/hi.js";
import { localizedMonthNames } from "../src/ui/date-value.js";
import { createWhoVaQuestionControls } from "../src/ui/question-controls.js";

const dateInstrument: InstrumentDefinition = {
  id: "date-control-test",
  title: "Date control test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [
    {
      name: "dates",
      sourceRow: 1,
      order: 1,
      label: { en: "Dates" }
    }
  ],
  questions: [
    {
      name: "Id10021",
      order: 1,
      sourceRow: 2,
      sourceType: "date",
      dataType: "date",
      control: "date",
      label: { en: "(Id10021) [When was the deceased born?]" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["dates"]
    },
    {
      name: "Id10024",
      order: 2,
      sourceRow: 3,
      sourceType: "date",
      dataType: "date",
      control: "date",
      appearance: "year",
      label: { en: "(Id10024) [Please indicate the year of death.]" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["dates"]
    },
    {
      name: "dob_month_year",
      order: 3,
      sourceRow: 4,
      sourceType: "date",
      dataType: "date",
      control: "date",
      appearance: "month-year",
      label: { en: "Birth month and year" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["dates"]
    },
    {
      name: "readonly_month_year",
      order: 4,
      sourceRow: 5,
      sourceType: "date",
      dataType: "date",
      control: "date",
      appearance: "month-year",
      label: { en: "Read-only birth month and year" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      sectionPath: ["dates"]
    }
  ]
};

const BareView = ({ children }: { children?: React.ReactNode }) => <>{children}</>;
const BareText = ({ children }: { children?: React.ReactNode }) => <>{children}</>;

describe("web date controls", () => {
  it("renders exact dates as calendars and partial dates as localized selectors", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const changes: Record<string, unknown>[] = [];
    root.render(
      <WhoVaForm
        instrument={dateInstrument}
        locale="hi"
        uiTranslations={{ hi: hindi.ui ?? {} }}
        onChange={(next) => changes.push(next)}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    const input = container.querySelector<HTMLInputElement>('[data-testid="question-Id10021"]');
    expect(input?.type).toBe("date");

    const yearSelect = container.querySelector<HTMLSelectElement>('[data-testid="question-Id10024-year"]');
    expect(yearSelect?.tagName).toBe("SELECT");
    const monthSelect = container.querySelector<HTMLSelectElement>(
      '[data-testid="question-dob_month_year-month"]'
    );
    const partialYearSelect = container.querySelector<HTMLSelectElement>(
      '[data-testid="question-dob_month_year-year"]'
    );
    const readOnlyMonthSelect = container.querySelector<HTMLSelectElement>(
      '[data-testid="question-readonly_month_year-month"]'
    );
    const readOnlyYearSelect = container.querySelector<HTMLSelectElement>(
      '[data-testid="question-readonly_month_year-year"]'
    );
    expect(monthSelect?.tagName).toBe("SELECT");
    expect(partialYearSelect?.tagName).toBe("SELECT");
    expect(readOnlyMonthSelect?.disabled).toBe(true);
    expect(readOnlyYearSelect?.disabled).toBe(true);
    expect(monthSelect?.querySelector('option[value=""]')?.textContent).toBe(hindi.ui?.selectDate);
    expect(monthSelect?.querySelector('option[value="04"]')?.textContent).toBe(localizedMonthNames("hi")[3]);

    const monthSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
    await act(async () => {
      monthSetter?.call(monthSelect, "04");
      monthSelect?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(changes.at(-1)?.dob_month_year).toBeUndefined();
    await act(async () => {
      monthSetter?.call(partialYearSelect, "1987");
      partialYearSelect?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(partialYearSelect?.value).toBe("1987");
    expect(changes.at(-1)?.dob_month_year).toBe("1987-04-01");
    await act(async () => {
      monthSetter?.call(monthSelect, "");
      monthSelect?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(changes.at(-1)?.dob_month_year).toBeUndefined();

    root.unmount();
    container.remove();
  });

  it("restores the prior partial date when validation rejects a selection", async () => {
    let selectYear: ((value: string) => void) | undefined;
    const ProbeSelect = (props: {
      accessibilityLabel?: string;
      onValueChange: (value: string) => void;
      value: string;
    }) => {
      if (props.accessibilityLabel === "Year") {
        selectYear = props.onValueChange;
      }
      return null;
    };
    const Controls = createWhoVaQuestionControls({
      View: BareView,
      Text: BareText,
      TextInput: "input",
      PartialSelect: ProbeSelect,
      Pressable: "button"
    });
    const container = document.createElement("div");
    const root = createRoot(container);
    const issues: unknown[] = [];
    const question = {
      ...dateInstrument.questions.find((candidate) => candidate.name === "dob_month_year")!,
      constraint: { source: ". <= date('1987-01-01')" }
    };
    const onAnswer = vi.fn();
    await act(async () => {
      root.render(
        <Controls.Date
          question={question}
          value="1987-04-01"
          data={{}}
          locale="en"
          issues={[]}
          onAnswer={onAnswer}
          onDraftIssue={(_questionName, issue) => issues.push(issue)}
        />
      );
    });
    await act(async () => {
      selectYear?.("1988");
    });
    expect(onAnswer).not.toHaveBeenCalled();
    expect(issues.at(-1)).toEqual(
      expect.objectContaining({ code: "constraint", question: "dob_month_year" })
    );
    root.unmount();
    container.remove();
  });

  it("clears a month when a year change would exceed the static date bound", async () => {
    let selectYear: ((value: string) => void) | undefined;
    let selectedMonth = "";
    let selectedYear = "";
    const issues: unknown[] = [];
    const ProbeSelect = (props: {
      accessibilityLabel?: string;
      onValueChange: (value: string) => void;
      value: string;
    }) => {
      if (props.accessibilityLabel === "Year") {
        selectYear = props.onValueChange;
        selectedYear = props.value;
      } else {
        selectedMonth = props.value;
      }
      return null;
    };
    const Controls = createWhoVaQuestionControls({
      View: BareView,
      Text: BareText,
      TextInput: "input",
      PartialSelect: ProbeSelect,
      Pressable: "button"
    });
    const question = {
      ...dateInstrument.questions.find((candidate) => candidate.name === "dob_month_year")!,
      constraint: { source: ". <= date('2026-10-03')" }
    };
    const root = createRoot(document.createElement("div"));
    const onAnswer = vi.fn();
    await act(async () =>
      root.render(
        <Controls.Date
          question={question}
          value="2025-12-01"
          data={{}}
          locale="en"
          issues={[]}
          onAnswer={onAnswer}
          onDraftIssue={(_questionName, issue) => issues.push(issue)}
        />
      )
    );
    await act(async () => {
      selectYear?.("2026");
    });
    expect(selectedYear).toBe("2026");
    expect(selectedMonth).toBe("");
    expect(onAnswer).not.toHaveBeenCalled();
    expect(issues.at(-1)).toEqual(expect.objectContaining({ code: "constraint" }));
    root.unmount();
  });

  it("does not swallow an unexpected host callback error", async () => {
    let selectYear: ((value: string) => void) | undefined;
    const ProbeSelect = (props: { onValueChange: (value: string) => void }) => {
      selectYear = props.onValueChange;
      return null;
    };
    const Controls = createWhoVaQuestionControls({
      View: BareView,
      Text: BareText,
      TextInput: "input",
      PartialSelect: ProbeSelect,
      Pressable: "button"
    });
    const question = dateInstrument.questions.find((candidate) => candidate.name === "dob_month_year")!;
    const root = createRoot(document.createElement("div"));
    await act(async () =>
      root.render(
        <Controls.Date
          question={question}
          value="1987-04-01"
          data={{}}
          locale="en"
          issues={[]}
          onAnswer={() => {
            throw new Error("unexpected host failure");
          }}
        />
      )
    );
    expect(() => selectYear?.("1988")).toThrow("unexpected host failure");
    root.unmount();
  });
});
