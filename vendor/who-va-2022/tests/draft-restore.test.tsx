// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  WHO_VA_FORM_VERSION,
  type InstrumentDefinition,
  type WhoVaDraft,
  type WhoVaSession
} from "../src/index.js";
import { defineWhoVaElement, type WhoVaFormElement } from "../src/web-component.js";
import { WhoVaForm } from "../src/web.js";

const instrument: InstrumentDefinition = {
  id: "draft-restore-test",
  title: "Draft restore test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "draft-restore-test.json",
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

function clickNext(container: HTMLElement) {
  const next = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
    (candidate) => candidate.textContent === "Next"
  );
  next?.click();
}

function savedDraft(overrides: Partial<WhoVaDraft>): WhoVaDraft {
  return {
    schemaVersion: 1,
    formVersion: WHO_VA_FORM_VERSION,
    id: "draft-1",
    instrumentId: instrument.id,
    instrumentVersion: instrument.version,
    currentSection: "two",
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    data: { "question-one": "Restored answer" },
    ...overrides
  };
}

afterEach(() => document.body.replaceChildren());

describe("draft restore on mount (digitva-ybz)", () => {
  it("loads the draft on first mount, applies its data and section, and does not save before that settles", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    let resolveLoad: ((draft: WhoVaDraft) => void) | undefined;
    const load = vi.fn(() => new Promise<WhoVaDraft>((resolve) => (resolveLoad = resolve)));
    const save = vi.fn(async (_draft: WhoVaDraft) => undefined);
    let session: WhoVaSession | undefined;

    root.render(
      <WhoVaForm
        instrument={instrument}
        draftId="draft-1"
        draftStore={{ save, load }}
        onReady={(s) => (session = s)}
      />
    );
    await vi.waitFor(() => expect(load).toHaveBeenCalledWith("draft-1"));

    // A section switch during the still-pending restore must not overwrite
    // the server's draft with the form's (still empty) initial state.
    clickNext(container);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(save).not.toHaveBeenCalled();

    resolveLoad?.(savedDraft({}));
    await vi.waitFor(() => expect(session?.getSnapshot().data["question-one"]).toBe("Restored answer"));
    expect(session?.getSnapshot().currentSection.name).toBe("two");

    // Now that the restore has settled, a save goes through and carries the
    // restored answer forward rather than the pre-restore empty state.
    clickNext(container);
    await vi.waitFor(() => expect(save).toHaveBeenCalled());
    expect(save.mock.calls[0]?.[0]).toMatchObject({ data: { "question-one": "Restored answer" } });
    root.unmount();
  });

  it("never saves for the rest of the mount when the load fails", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const load = vi.fn(async () => {
      throw new Error("network down");
    });
    const save = vi.fn(async () => undefined);
    const onDraftError = vi.fn();

    root.render(
      <WhoVaForm
        instrument={instrument}
        draftId="draft-1"
        draftStore={{ save, load }}
        onDraftError={onDraftError}
      />
    );
    await vi.waitFor(() =>
      expect(onDraftError).toHaveBeenCalledWith(expect.objectContaining({ message: "network down" }))
    );

    clickNext(container);
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(save).not.toHaveBeenCalled();
    root.unmount();
  });
});

describe("locale switch keeps answers (digitva-ybz)", () => {
  it("keeps the session's answers when the host re-supplies a translated copy of the same instrument", async () => {
    defineWhoVaElement("who-va-locale-switch-test");
    const element = document.createElement("who-va-locale-switch-test") as WhoVaFormElement;
    element.instrument = instrument;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    element.setData({ "question-one": "Interviewer's answer" });
    expect(element.getData()["question-one"]).toBe("Interviewer's answer");

    // Same id and version, but a distinct object -- exactly what applying a
    // locale's translations produces (translations.js clones the instrument).
    const translated: InstrumentDefinition = {
      ...instrument,
      questions: instrument.questions.map((q) => ({ ...q, label: { ...q.label, hi: `${q.label.en} (hi)` } }))
    };
    element.instrument = translated;
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(element.getData()["question-one"]).toBe("Interviewer's answer");
    element.remove();
  });

  it("starts a fresh session when the instrument id changes", async () => {
    defineWhoVaElement("who-va-locale-switch-fresh-test");
    const element = document.createElement("who-va-locale-switch-fresh-test") as WhoVaFormElement;
    element.instrument = instrument;
    document.body.append(element);
    await new Promise((resolve) => setTimeout(resolve, 0));

    element.setData({ "question-one": "Interviewer's answer" });
    element.instrument = { ...instrument, id: "a-different-questionnaire" };
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(element.getData()["question-one"]).toBeUndefined();
    element.remove();
  });
});
