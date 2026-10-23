// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { WhoVaForm, WhoVaQuestionControls } from "../src/web.js";
import type { InstrumentDefinition, InstrumentQuestion } from "../src/index.js";

const base = {
  sourceRow: 1,
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["s"]
};
const LONG = `Interviewer: ${"read this note carefully and slowly. ".repeat(6)}`;

const instrument: InstrumentDefinition = {
  id: "condense-test",
  title: "Condense test",
  version: "1",
  defaultLanguage: "English (en)",
  sourceFile: "generated-test-artifact.json",
  sections: [{ name: "s", sourceRow: 1, order: 1, label: { en: "S" } }],
  questions: [
    { ...base, name: "narr_audio", order: 1, sourceType: "audio", dataType: "attachment", control: "audio",
      label: { en: "(narr_audio) Tell me in your own words what happened." }, hint: { en: "Record it." } },
    { ...base, name: "narr", order: 2, sourceType: "text", dataType: "string", control: "text",
      label: { en: "(narr) Tell me in your own words what happened." }, hint: { en: "Or type it." } },
    { ...base, name: "note1", order: 3, sourceType: "note", dataType: "none", control: "note", readOnly: true,
      label: { en: LONG }, hint: {} }
  ] as InstrumentQuestion[]
};

async function mount(condensePrompts: boolean) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  root.render(<WhoVaForm instrument={instrument} condensePrompts={condensePrompts} />);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return { container, unmount: () => { root.unmount(); container.remove(); } };
}

describe("condensePrompts", () => {
  it("shows a repeated prompt once and keeps both answer modes and hints", async () => {
    const on = await mount(true);
    expect(on.container.textContent?.match(/Tell me in your own words/g)).toHaveLength(1);
    expect(on.container.textContent).toContain("Record it.");
    expect(on.container.textContent).toContain("Or type it.");
    on.unmount();

    const off = await mount(false);
    expect(off.container.textContent?.match(/Tell me in your own words/g)).toHaveLength(2);
    off.unmount();
  });
});

describe("saved audio and a refused microphone on a host without a web player", () => {
  it("plays a saved recording with the host's own player and reports a NotAllowedError that is not a DOMException", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const denied = Object.assign(new Error("denied"), { name: "NotAllowedError" });
    const Player = vi.fn(() => <div data-testid="host-player" />);
    root.render(
      <WhoVaQuestionControls.Audio
        question={instrument.questions[0]!}
        value={{ id: "a", uri: "file:///a.m4a", mimeType: "audio/mp4" } as never}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ AudioPlayer: Player, startAudioRecording: vi.fn().mockRejectedValue(denied) }}
        onAnswer={vi.fn()}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    await vi.waitFor(() => expect(container.querySelector('[data-testid="host-player"]')).not.toBeNull());
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("Microphone permission was denied")
    );
    root.unmount();
    container.remove();
  });
});

describe("deleting a saved recording", () => {
  it("offers Delete recording, removes the stored file and clears the answer", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const removeAttachment = vi.fn().mockResolvedValue(undefined);
    const onAnswer = vi.fn();
    const saved = { id: "a", uri: "who-va-attachment:a", mimeType: "audio/mp4" } as never;
    root.render(
      <WhoVaQuestionControls.Audio
        question={instrument.questions[0]!}
        value={saved}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ removeAttachment, startAudioRecording: vi.fn() }}
        onAnswer={onAnswer}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio-remove"]')?.click();
    await vi.waitFor(() => expect(onAnswer).toHaveBeenCalledWith(undefined));
    expect(removeAttachment).toHaveBeenCalledWith(saved);
    root.unmount();
    container.remove();
  });
});
