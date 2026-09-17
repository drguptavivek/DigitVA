// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { WHO_VA_FORM_VERSION, type InstrumentDefinition, type WhoVaDraft } from "../src/index.js";
import { WhoVaForm } from "../src/web.js";

const instrument: InstrumentDefinition = {
  id: "draft-order-test",
  title: "Draft order test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "draft-order-test.json",
  sections: [
    { name: "one", sourceRow: 1, order: 1, label: { en: "One" } },
    { name: "two", sourceRow: 3, order: 2, label: { en: "Two" } },
    { name: "three", sourceRow: 5, order: 3, label: { en: "Three" } }
  ],
  questions: [
    ...["one", "two", "three"].map((section, index) => ({
      name: `question-${section}`,
      order: index + 1,
      sourceRow: index * 2 + 2,
      sourceType: "text",
      dataType: "string" as const,
      control: "text" as const,
      label: { en: `Question ${section}` },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: [section]
    }))
  ]
};

afterEach(() => document.body.replaceChildren());

describe("draft save ordering", () => {
  it("waits for an older store write before starting a newer write", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    let finishFirstSave: (() => void) | undefined;
    const saved: WhoVaDraft[] = [];
    const save = vi.fn(async (draft: WhoVaDraft) => {
      saved.push(draft);
      if (saved.length === 1)
        await new Promise<void>((resolve) => {
          finishFirstSave = resolve;
        });
    });

    root.render(<WhoVaForm instrument={instrument} draftStore={{ save }} />);
    await vi.waitFor(() => expect(container.textContent).toContain("Section 1 of 3"));
    const next = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
      (candidate) => candidate.textContent === "Next"
    );

    next?.click();
    next?.click();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(saved[0]?.formVersion).toBe(WHO_VA_FORM_VERSION);
    expect(saved[0]?.currentSection).toBe("two");

    finishFirstSave?.();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(saved[1]?.currentSection).toBe("three");
    root.unmount();
  });
});
