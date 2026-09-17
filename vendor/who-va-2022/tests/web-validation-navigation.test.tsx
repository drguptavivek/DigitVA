// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { whoVa2022Instrument, type InstrumentDefinition } from "../src/index.js";
import { WhoVaForm } from "../src/web.js";

const requiredInstrument: InstrumentDefinition = {
  id: "validation-navigation-test",
  title: "Validation navigation test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "details", sourceRow: 1, order: 1, label: { en: "Details" } }],
  questions: [
    {
      name: "required_name",
      order: 1,
      sourceRow: 2,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Required name" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["details"]
    }
  ]
};
const requiredControlInstrument: InstrumentDefinition = {
  id: "validation-control-test",
  title: "Validation control test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "controls", sourceRow: 1, order: 1, label: { en: "Controls" } }],
  questions: [
    {
      name: "required_choice",
      order: 1,
      sourceRow: 2,
      sourceType: "select_one yes_no",
      dataType: "string",
      control: "singleChoice",
      listName: "yes_no",
      label: { en: "Required choice" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["controls"],
      choices: [
        { value: "yes", sourceRow: 3, label: { en: "Yes" } },
        { value: "no", sourceRow: 4, label: { en: "No" } }
      ]
    },
    {
      name: "required_multi",
      order: 2,
      sourceRow: 5,
      sourceType: "select_multiple symptom",
      dataType: "string[]",
      control: "multipleChoice",
      listName: "symptom",
      label: { en: "Required symptoms" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["controls"],
      choices: [
        { value: "fever", sourceRow: 6, label: { en: "Fever" } },
        { value: "cough", sourceRow: 7, label: { en: "Cough" } }
      ]
    },
    {
      name: "required_confirm",
      order: 3,
      sourceRow: 8,
      sourceType: "trigger",
      dataType: "boolean",
      control: "confirm",
      label: { en: "Required confirmation" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["controls"]
    },
    {
      name: "required_file",
      order: 4,
      sourceRow: 9,
      sourceType: "file",
      dataType: "attachment",
      control: "file",
      label: { en: "Required file" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["controls"]
    }
  ]
};
const crossSectionInstrument: InstrumentDefinition = {
  id: "cross-section-validation-test",
  title: "Cross-section validation test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [
    { name: "identity", sourceRow: 1, order: 1, label: { en: "Identity" } },
    { name: "details", sourceRow: 3, order: 2, label: { en: "Details" } }
  ],
  questions: [
    {
      name: "required_name",
      order: 1,
      sourceRow: 2,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Required name" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["identity"]
    },
    {
      name: "case_detail",
      order: 2,
      sourceRow: 4,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Case detail" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["details"]
    }
  ]
};

afterEach(() => {
  document.body.replaceChildren();
  Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
});

describe("validation navigation", () => {
  it("shows and clears constraint errors while the interviewer is typing", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<WhoVaForm instrument={whoVa2022Instrument} />);
    });
    const input = container.querySelector<HTMLInputElement>('[data-testid="question-Id10010a"]');
    const setNativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    expect(input).not.toBeNull();
    expect(setNativeValue).toBeDefined();

    await act(async () => {
      setNativeValue?.call(input, "3");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(container.textContent).toContain("Interviewer should be an adult and not older than 89");
    expect(input?.getAttribute("aria-invalid")).toBe("true");

    await act(async () => {
      setNativeValue?.call(input, "33");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(container.textContent).not.toContain("Interviewer should be an adult and not older than 89");
    expect(input?.hasAttribute("aria-invalid")).toBe(false);
    root.unmount();
  });

  it("renders locked initial answers as read-only and keeps their original value", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <WhoVaForm
          instrument={requiredInstrument}
          initialData={{ required_name: "Case Entry Name" }}
          lockedQuestionNames={["required_name"]}
        />
      );
    });

    const input = container.querySelector<HTMLInputElement>('[data-testid="question-required_name"]');
    expect(input?.value).toBe("Case Entry Name");
    expect(input?.getAttribute("aria-readonly")).toBe("true");

    const setNativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setNativeValue?.call(input, "Edited Name");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    expect(input?.value).toBe("Case Entry Name");
    root.unmount();
  });

  it("marks non-text required controls invalid after validation", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<WhoVaForm instrument={requiredControlInstrument} />);
    });

    const complete = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "Complete"
    );
    await act(async () => {
      complete?.click();
    });

    await vi.waitFor(() =>
      expect(
        container
          .querySelector('[data-testid="question-required_choice-choice-yes"]')
          ?.getAttribute("aria-invalid")
      ).toBe("true")
    );
    expect(
      container
        .querySelector('[data-testid="question-required_multi-choice-fever"]')
        ?.getAttribute("aria-invalid")
    ).toBe("true");
    expect(
      container.querySelector('[data-testid="question-required_confirm"]')?.getAttribute("aria-invalid")
    ).toBe("true");
    expect(
      container.querySelector('[data-testid="question-required_file"]')?.getAttribute("aria-invalid")
    ).toBe("true");
    expect(container.textContent).toContain("Required choice is required");
    expect(container.textContent).toContain("Required symptoms is required");
    expect(container.textContent).toContain("Required confirmation is required");
    expect(container.textContent).toContain("Required file is required");

    root.unmount();
  });
  it("scrolls to and focuses the first invalid question after Next", async () => {
    const scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView
    });
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(<WhoVaForm instrument={requiredInstrument} />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const next = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "Complete"
    );
    next?.click();
    await vi.waitFor(() => expect(scrollIntoView).toHaveBeenCalledOnce());
    expect(scrollIntoView).toHaveBeenCalledWith({ behavior: "smooth", block: "start" });

    const input = container.querySelector<HTMLInputElement>('[data-testid="question-required_name"]');
    expect(document.activeElement).toBe(input);

    root.unmount();
  });

  it("returns to the incomplete section when final completion validation fails", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<WhoVaForm instrument={crossSectionInstrument} />);
    });

    const details = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "2. Details"
    );
    await act(async () => {
      details?.click();
    });

    const input = container.querySelector<HTMLInputElement>('[data-testid="question-case_detail"]');
    const setNativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setNativeValue?.call(input, "Completed detail");
      input?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const complete = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "Complete"
    );
    await act(async () => {
      complete?.click();
    });

    await vi.waitFor(() => expect(container.textContent).toContain("Required name is required"));
    expect(container.textContent).toContain("Identity");
    expect(container.querySelector('[data-testid="question-required_name"]')).not.toBeNull();
    expect(
      Array.from(container.querySelectorAll<HTMLElement>('[role="button"]'))
        .find((button) => button.textContent === "1. Identity")
        ?.getAttribute("aria-invalid")
    ).toBe("true");

    root.unmount();
  });

  it("marks sections and questions completed after their required answers are filled", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(<WhoVaForm instrument={crossSectionInstrument} />);
    });

    expect(container.querySelector('[data-testid="section-status-identity"]')).toBeNull();
    expect(container.querySelector('[data-testid="question-status-required_name"]')).toBeNull();

    const nameInput = container.querySelector<HTMLInputElement>('[data-testid="question-required_name"]');
    const setNativeValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    await act(async () => {
      setNativeValue?.call(nameInput, "Completed name");
      nameInput?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await vi.waitFor(() =>
      expect(container.querySelector('[data-testid="section-status-identity"]')?.textContent).toBe("✓")
    );
    expect(container.querySelector('[data-testid="question-status-required_name"]')?.textContent).toBe("✓");
    expect(
      Array.from(container.querySelectorAll<HTMLElement>('[role="button"]'))
        .find((button) => button.getAttribute("aria-label")?.includes("Identity"))
        ?.getAttribute("aria-label")
    ).toContain("completed");

    const details = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "2. Details"
    );
    await act(async () => {
      details?.click();
    });

    const detailInput = container.querySelector<HTMLInputElement>('[data-testid="question-case_detail"]');
    await act(async () => {
      setNativeValue?.call(detailInput, "Completed detail");
      detailInput?.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await vi.waitFor(() =>
      expect(container.querySelector('[data-testid="section-status-details"]')?.textContent).toBe("✓")
    );
    expect(container.querySelector('[data-testid="question-status-case_detail"]')?.textContent).toBe("✓");

    root.unmount();
  });
});
