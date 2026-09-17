// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWhoVaSession, type InstrumentDefinition, type WhoVaDraft } from "../src/index.js";
import { createInsecureWhoVaBrowserDefaults, WhoVaForm } from "../src/web.js";

const previewInstrument: InstrumentDefinition = {
  id: "preview-test",
  title: "Preview test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [
    { name: "identity", sourceRow: 1, order: 1, label: { en: "Identity" } },
    { name: "history", sourceRow: 3, order: 2, label: { en: "History" } }
  ],
  questions: [
    {
      name: "name",
      order: 1,
      sourceRow: 2,
      sourceType: "text",
      dataType: "string",
      control: "text",
      label: { en: "Name" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      sectionPath: ["identity"]
    },
    {
      name: "symptom",
      order: 2,
      sourceRow: 4,
      sourceType: "select_one symptom",
      dataType: "string",
      control: "singleChoice",
      label: { en: "Main symptom" },
      hint: {},
      guidance: {},
      required: false,
      readOnly: false,
      constraintMessage: {},
      choices: [
        { value: "fever", sourceRow: 5, label: { en: "Fever" } },
        { value: "cough", sourceRow: 6, label: { en: "Cough" } }
      ],
      sectionPath: ["history"]
    }
  ]
};

afterEach(() => {
  document.body.replaceChildren();
  history.replaceState(null, "");
  localStorage.clear();
});

function button(container: HTMLElement, label: string): HTMLElement | undefined {
  return Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
    (candidate) => candidate.textContent === label || candidate.getAttribute("aria-label") === label
  );
}

describe("answer preview", () => {
  it("does not restore or follow history for a different configured draft", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const foreignDraft: WhoVaDraft = {
      schemaVersion: 1,
      formVersion: "2022",
      id: "draft-a",
      instrumentId: previewInstrument.id,
      instrumentVersion: previewInstrument.version,
      currentSection: "history",
      createdAt: "2026-07-20T00:00:00.000Z",
      updatedAt: "2026-07-20T00:00:00.000Z",
      data: { name: "Foreign respondent", symptom: "fever" }
    };
    const load = vi.fn(async (id: string) => (id === foreignDraft.id ? foreignDraft : undefined));
    history.replaceState(
      {
        __whoVaFormNavigation: {
          instrumentId: previewInstrument.id,
          draftId: foreignDraft.id,
          currentSection: foreignDraft.currentSection,
          view: "preview"
        }
      },
      ""
    );

    root.render(
      <WhoVaForm instrument={previewInstrument} draftId="draft-b" draftStore={{ save: vi.fn(), load }} />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(load).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Foreign respondent");

    history.pushState(
      {
        __whoVaFormNavigation: {
          instrumentId: previewInstrument.id,
          draftId: foreignDraft.id,
          currentSection: foreignDraft.currentSection,
          view: "preview"
        }
      },
      ""
    );
    window.dispatchEvent(new PopStateEvent("popstate"));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(load).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("Foreign respondent");
    root.unmount();
  });

  it("keeps answers out of browser history state", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const session = createWhoVaSession(previewInstrument, {
      initialData: { name: "Sensitive respondent name" }
    });

    root.render(<WhoVaForm instrument={previewInstrument} session={session} />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(JSON.stringify(history.state)).not.toContain("Sensitive respondent name");
    expect(JSON.stringify(history.state)).not.toContain('"data"');
    root.unmount();
  });

  it("returns to the same section with responses preserved", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const session = createWhoVaSession(previewInstrument, { initialData: { name: "Amina" } });
    expect(session.next().advanced).toBe(true);
    session.setAnswer("symptom", "fever");
    root.render(<WhoVaForm instrument={previewInstrument} session={session} />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container.textContent).toContain("Section 2 of 2");
    button(container, "Preview answers")?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container.textContent).toContain("Answer preview");
    expect(container.textContent).toContain("Name");
    expect(container.textContent).toContain("Amina");
    expect(container.textContent).toContain("Main symptom");
    expect(container.textContent).toContain("Fever");

    button(container, "Back to form")?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(container.textContent).toContain("Section 2 of 2");
    expect(session.getSnapshot().data.symptom).toBe("fever");
    root.unmount();
  });

  it("restores the preview and current section after a browser reload", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const session = createWhoVaSession(previewInstrument, { initialData: { name: "Amina" } });
    expect(session.next().advanced).toBe(true);
    session.setAnswer("symptom", "fever");

    const firstRoot = createRoot(container);
    const insecureDefaults = createInsecureWhoVaBrowserDefaults();
    firstRoot.render(
      <WhoVaForm instrument={previewInstrument} session={session} draftStore={insecureDefaults.draftStore} />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    button(container, "Preview answers")?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Answer preview"));
    expect(container.textContent).toContain("Answer preview");
    expect(JSON.stringify(history.state)).not.toContain('"data"');
    expect(Object.keys(localStorage).some((key) => key.startsWith("who-va-2022:draft:"))).toBe(true);
    firstRoot.unmount();

    const reloadedRoot = createRoot(container);
    reloadedRoot.render(
      <WhoVaForm instrument={previewInstrument} draftStore={insecureDefaults.draftStore} />
    );
    await vi.waitFor(() => expect(container.textContent).toContain("Amina"));
    expect(container.textContent).toContain("Answer preview");
    expect(container.textContent).toContain("Fever");
    button(container, "Back to form")?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(container.textContent).toContain("Section 2 of 2");
    reloadedRoot.unmount();
  });
});
