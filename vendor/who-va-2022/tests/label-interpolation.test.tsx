// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import { WhoVaForm } from "../src/web.js";
import type { InstrumentDefinition } from "../src/index.js";

const instrument: InstrumentDefinition = {
  id: "label-interpolation-test",
  title: "Label interpolation test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "age", sourceRow: 1, order: 1, label: { en: "Age" } }],
  questions: [
    {
      name: "birthDate",
      order: 1,
      sourceRow: 2,
      sourceType: "system",
      dataType: "date",
      control: "system",
      label: {},
      hint: {},
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      sectionPath: ["age"]
    },
    {
      name: "deathDate",
      order: 2,
      sourceRow: 3,
      sourceType: "system",
      dataType: "date",
      control: "system",
      label: {},
      hint: {},
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      sectionPath: ["age"]
    },
    {
      name: "ageInDays",
      order: 3,
      sourceRow: 4,
      sourceType: "calculate",
      dataType: "calculated",
      control: "calculated",
      label: {},
      hint: {},
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      calculation: { source: "${deathDate} - ${birthDate}" },
      sectionPath: ["age"]
    },
    {
      name: "ageInDaysDoubled",
      order: 4,
      sourceRow: 5,
      sourceType: "calculate",
      dataType: "calculated",
      control: "calculated",
      label: {},
      hint: {},
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      calculation: { source: "${ageInDays} * 2" },
      sectionPath: ["age"]
    },
    {
      name: "displayAgeNeonate",
      order: 5,
      sourceRow: 6,
      sourceType: "note",
      dataType: "none",
      control: "note",
      label: { en: "NEONATE was ${ageInDays} days old." },
      hint: { en: "Sequential check: ${ageInDaysDoubled}." },
      guidance: {},
      required: false,
      readOnly: true,
      constraintMessage: {},
      sectionPath: ["age"]
    }
  ]
};

describe("XLSForm label references", () => {
  it("renders values from sequential calculations in labels and hints", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);

    root.render(
      <WhoVaForm instrument={instrument} initialData={{ birthDate: "2026-06-20", deathDate: "2026-07-17" }} />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container.textContent).toContain("NEONATE was 27 days old.");
    expect(container.textContent).toContain("Sequential check: 54.");
    expect(container.textContent).not.toContain("${ageInDays}");

    root.unmount();
    container.remove();
  });
});
