// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { WhoVaForm } from "../src/web.js";
import type { InstrumentDefinition } from "../src/index.js";

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
    }
  ]
};

describe("web date controls", () => {
  it("renders WHO date questions with the browser calendar input", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(<WhoVaForm instrument={dateInstrument} />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    const input = container.querySelector<HTMLInputElement>('[data-testid="question-Id10021"]');
    expect(input?.type).toBe("date");

    const yearInput = container.querySelector<HTMLInputElement>('[data-testid="question-Id10024"]');
    expect(yearInput?.type).not.toBe("date");
    expect(yearInput?.placeholder).toBe("YYYY");

    root.unmount();
    container.remove();
  });
});
