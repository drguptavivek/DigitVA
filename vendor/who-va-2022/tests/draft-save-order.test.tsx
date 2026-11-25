// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createWhoVaSession } from "../src/engine/session.js";
import {
  WHO_VA_FORM_VERSION,
  type InstrumentDefinition,
  type WhoVaDraft,
  type WhoVaDraftController
} from "../src/index.js";
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

afterEach(() => {
  document.body.replaceChildren();
  // The web form keeps its section in history state; the next test starts clean.
  window.history.replaceState(null, "");
});

describe("draft save ordering", () => {
  it("waits for an older store write before starting a newer write", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    let finishFirstSave: (() => void) | undefined;
    let onRestored: (() => void) | undefined;
    const saved: WhoVaDraft[] = [];
    const save = vi.fn(async (draft: WhoVaDraft) => {
      saved.push(draft);
      if (saved.length === 1)
        await new Promise<void>((resolve) => {
          finishFirstSave = resolve;
        });
    });

    // saveDraft ignores calls until the mount-time draft restore settles
    // (digitva-ybz), so wait for that signal instead of the first render.
    const restored = new Promise<void>((resolve) => {
      onRestored = resolve;
    });
    root.render(
      <WhoVaForm instrument={instrument} draftStore={{ save }} onDraftRestored={() => onRestored?.()} />
    );
    await restored;
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

  async function mountHeld(extra: Record<string, unknown> = {}) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const session = createWhoVaSession(instrument, {});
    const saved: WhoVaDraft[] = [];
    const releases: Array<() => void> = [];
    const save = vi.fn(async (draft: WhoVaDraft) => {
      saved.push(draft);
      await new Promise<void>((resolve) => releases.push(resolve));
    });
    let controller: WhoVaDraftController | undefined;
    let onRestored: (() => void) | undefined;
    const restored = new Promise<void>((resolve) => {
      onRestored = resolve;
    });
    root.render(
      <WhoVaForm
        instrument={instrument}
        session={session}
        draftStore={{ save }}
        autoSaveDraftIntervalMs={false}
        onDraftRestored={() => onRestored?.()}
        onDraftController={(next) => {
          controller = next;
        }}
        {...extra}
      />
    );
    await restored;
    await vi.waitFor(() => expect(controller).toBeDefined());
    const button = (label: string) =>
      Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find(
        (candidate) => candidate.textContent === label
      );
    return { container, root, session, save, saved, releases, controller: () => controller!, button };
  }

  it("coalesces every save asked for while one is in flight into one waiting save of the latest answers", async () => {
    const { root, session, save, saved, releases, controller } = await mountHeld();
    session.setAnswer("question-one", "a");
    const first = controller().saveDraft();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    const later: Promise<void>[] = [];
    for (const value of ["b", "c", "d", "e"]) {
      session.setAnswer("question-one", value);
      later.push(controller().saveDraft());
    }
    let laterSettled = false;
    void Promise.all(later).then(() => {
      laterSettled = true;
    });
    releases[0]?.();
    await first;
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(2));
    expect(saved[0]?.data["question-one"]).toBe("a");
    expect(saved[1]?.data["question-one"]).toBe("e");
    // The waiting callers settle only once the save that carries their answers does.
    await Promise.resolve();
    expect(laterSettled).toBe(false);
    releases[1]?.();
    await Promise.all(later);
    expect(save).toHaveBeenCalledTimes(2);
    root.unmount();
  });

  it("does not save on an answer change without autoSaveDraftOnChange, but does on Next", async () => {
    const { root, session, save, saved, releases, button } = await mountHeld();
    session.setAnswer("question-one", "typed");
    await new Promise((resolve) => setTimeout(resolve, 20));
    expect(save).not.toHaveBeenCalled();
    button("Next")?.click();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(saved[0]?.currentSection).toBe("two");
    expect(saved[0]?.data["question-one"]).toBe("typed");
    releases[0]?.();
    root.unmount();
  });

  it("moves back at once on Previous while the save is still in flight", async () => {
    const { container, root, save, releases, button } = await mountHeld();
    button("Next")?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Section 2 of 3"));
    releases[0]?.();
    await vi.waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 0));
    const back = Array.from(container.querySelectorAll<HTMLElement>('[role="button"]')).find((candidate) =>
      /Back|Previous/.test(candidate.textContent ?? "")
    );
    back?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Section 1 of 3"));
    // The section changed while the Previous save is still out.
    expect(save).toHaveBeenCalledTimes(2);
    expect(releases).toHaveLength(2);
    releases[1]?.();
    root.unmount();
  });
});
