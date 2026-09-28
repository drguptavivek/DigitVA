// @vitest-environment jsdom

/** Round-3 presentation: DD-MMM-YYYY date parts, inline messages, attachment notes, stepper fit. */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentDefinition, ValidationIssue } from "../src/index.js";
import { formatDdMmmYyyy, isoFromParts, localizedMonthNames } from "../src/ui/date-value.js";
import { stepperFits } from "../src/ui/section-navigation.js";
import hindi from "../src/languages/hi.js";
import { WhoVaForm } from "../src/web.js";

const HINDI = { locale: "hi", uiTranslations: { hi: hindi.ui ?? {} } } as const;

const instrument: InstrumentDefinition = {
  id: "round3-test",
  title: "Round 3 test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "one", sourceRow: 1, order: 1, label: { en: "One", hi: "एक" } }],
  questions: [
    {
      name: "born",
      order: 1,
      sourceRow: 2,
      sourceType: "date",
      dataType: "date",
      control: "date",
      label: { en: "(Id10021) When was the deceased born?", hi: "(Id10021) मृतक का जन्म कब हुआ?" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["one"]
    },
    {
      name: "story",
      order: 2,
      sourceRow: 3,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Thank you. Now tell me in your own words about the events that led to the death?" },
      hint: {},
      guidance: {},
      required: true,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["one"]
    },
    {
      name: "voice",
      order: 3,
      sourceRow: 4,
      sourceType: "audio",
      dataType: "attachment",
      control: "audio",
      label: { en: "Record the narrative" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["one"]
    }
  ]
};

const setValue = (input: HTMLInputElement | null, value: string) => {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, value);
  input?.dispatchEvent(new Event("input", { bubbles: true }));
};
const byTestId = <T extends HTMLElement>(container: HTMLElement, id: string) =>
  container.querySelector<T>(`[data-testid="${id}"]`);

afterEach(() => {
  document.body.replaceChildren();
});

async function mount(props: Partial<React.ComponentProps<typeof WhoVaForm>> = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const data: Record<string, unknown>[] = [];
  const issues: ValidationIssue[][] = [];
  await act(async () => {
    root.render(
      <WhoVaForm
        instrument={instrument}
        onChange={(next) => data.push(next)}
        onValidation={(next) => issues.push(next)}
        {...props}
      />
    );
  });
  return { container, root, data, issues };
}

describe("DD-MMM-YYYY date parts", () => {
  it("formats and parses without touching the stored ISO value", () => {
    expect(formatDdMmmYyyy("1986-07-16", "en")).toBe("16-Jul-1986");
    expect(isoFromParts("16", "07", "1986")).toBe("1986-07-16");
    expect(isoFromParts("6", "7", "1986")).toBe("1986-07-06");
    expect(isoFromParts("31", "02", "2020")).toBeUndefined();
    expect(isoFromParts("16", "07", "86")).toBeUndefined();
  });

  it("uses localized short month names", () => {
    expect(localizedMonthNames("hi")[6]).toMatch(/जुल/);
    expect(formatDdMmmYyyy("1986-07-16", "hi")).toMatch(/^16-जुल.*-1986$/);
  });

  it("stores ISO once all three parts make a date, nothing while partial, an error when impossible", async () => {
    const { container, root, data } = await mount();
    const day = byTestId<HTMLInputElement>(container, "question-born-day");
    const month = byTestId<HTMLSelectElement>(container, "question-born-month");
    const year = byTestId<HTMLInputElement>(container, "question-born-year");
    expect(month?.tagName).toBe("SELECT");
    expect(container.textContent).toContain("DD-MMM-YYYY");

    await act(async () => setValue(day, "16"));
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(month, "07");
      month?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(data.at(-1)?.born).toBeUndefined();
    await act(async () => setValue(year, "1986"));
    expect(data.at(-1)?.born).toBe("1986-07-16");
    expect(byTestId<HTMLInputElement>(container, "question-born")?.value).toBe("1986-07-16");

    await act(async () => setValue(day, "31"));
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      setter?.call(month, "02");
      month?.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(data.at(-1)?.born).toBeUndefined();
    await vi.waitFor(() => expect(container.textContent).toContain("Enter the date as DD-MMM-YYYY"));
    root.unmount();
  });

  it("names the parts in Hindi", async () => {
    const { container, root } = await mount(HINDI);
    expect(byTestId(container, "question-born-day")?.getAttribute("aria-label")).toBe("दिन");
    expect(byTestId(container, "question-born-year")?.getAttribute("aria-label")).toBe("वर्ष");
    root.unmount();
  });
});

describe("inline validation messages", () => {
  it("shows the short required message inline while the payload keeps the full one", async () => {
    const { container, root, issues } = await mount();
    const next = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "Complete"
    );
    await act(async () => {
      next?.click();
    });
    await vi.waitFor(() => expect(container.textContent).toContain("This question is required."));
    expect(container.textContent).not.toContain("led to the death? is required");
    expect(issues.at(-1)?.map((issue) => issue.message)).toContain(
      "Thank you. Now tell me in your own words about the events that led to the death? is required"
    );
    root.unmount();
  });

  it("is localized", async () => {
    const { container, root } = await mount(HINDI);
    const next = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (button) => button.textContent === "पूरा करें"
    );
    await act(async () => {
      next?.click();
    });
    await vi.waitFor(() => expect(container.textContent).toContain("यह प्रश्न आवश्यक है।"));
    root.unmount();
  });
});

describe("attachment controls without a host service", () => {
  it("explains why recording is unavailable and links the note to the button", async () => {
    const { container, root } = await mount();
    const button = byTestId(container, "question-voice");
    const note = byTestId(container, "question-voice-unavailable");
    expect(note?.textContent).toContain("Recording isn't available here yet");
    expect(button?.getAttribute("aria-disabled")).toBe("true");
    expect(button?.getAttribute("aria-describedby")).toBe("question-voice-unavailable");
    root.unmount();
  });

  it("shows no note when the host records audio", async () => {
    const { container, root } = await mount({
      platform: { captureAudio: async () => ({ uri: "blob:x", mimeType: "audio/webm" }) }
    });
    expect(byTestId(container, "question-voice-unavailable")).toBeNull();
    expect(byTestId(container, "question-voice")?.getAttribute("aria-disabled")).not.toBe("true");
    root.unmount();
  });
});

describe("horizontal stepper fit", () => {
  it("collapses rather than overflowing at tablet and phone widths", () => {
    // 820px tablet less the form's 16px gutters; 600px less the same.
    expect(stepperFits(788, 17)).toBe(true);
    expect(stepperFits(788, 30)).toBe(false);
    expect(stepperFits(568, 17)).toBe(false);
    expect(stepperFits(568, 30)).toBe(false);
    expect(stepperFits(358, 3)).toBe(true);
    expect(stepperFits(358, 11)).toBe(false);
  });
});
