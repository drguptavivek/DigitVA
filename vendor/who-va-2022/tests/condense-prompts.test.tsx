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
    // A saved recording: Replace asks first, then records.
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio"]')?.click();
    await vi.waitFor(() =>
      expect(container.querySelector('[data-testid="question-narr_audio-confirm-yes"]')).not.toBeNull()
    );
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio-confirm-yes"]')?.click();
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("Microphone permission was denied")
    );
    root.unmount();
    container.remove();
  });
});

describe("deleting or replacing a saved recording", () => {
  const saved = { id: "a", uri: "who-va-attachment:a", mimeType: "audio/mp4" } as never;
  async function renderSaved(startAudioRecording = vi.fn()) {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    const removeAttachment = vi.fn().mockResolvedValue(undefined);
    const onAnswer = vi.fn();
    root.render(
      <WhoVaQuestionControls.Audio
        question={instrument.questions[0]!}
        value={saved}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ removeAttachment, startAudioRecording }}
        onAnswer={onAnswer}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    const press = async (testId: string) => {
      await vi.waitFor(() => expect(container.querySelector(`[data-testid="${testId}"]`)).not.toBeNull());
      container.querySelector<HTMLElement>(`[data-testid="${testId}"]`)!.click();
    };
    const done = () => {
      root.unmount();
      container.remove();
    };
    return { container, removeAttachment, onAnswer, press, done };
  }

  it("asks before Delete recording, then removes the stored file and clears the answer", async () => {
    const view = await renderSaved();
    await view.press("question-narr_audio-remove");
    await vi.waitFor(() =>
      expect(view.container.querySelector('[data-testid="question-narr_audio-confirm"]')?.textContent).toContain(
        "Delete this recording?"
      )
    );
    expect(view.onAnswer).not.toHaveBeenCalled();
    expect(view.removeAttachment).not.toHaveBeenCalled();
    await view.press("question-narr_audio-confirm-yes");
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(undefined));
    expect(view.removeAttachment).toHaveBeenCalledWith(saved);
    view.done();
  });

  it("keeps the recording when the delete or replace prompt is cancelled", async () => {
    const startAudioRecording = vi.fn();
    const view = await renderSaved(startAudioRecording);
    for (const trigger of ["question-narr_audio-remove", "question-narr_audio"]) {
      await view.press(trigger);
      await view.press("question-narr_audio-confirm-cancel");
      await vi.waitFor(() =>
        expect(view.container.querySelector('[data-testid="question-narr_audio-confirm"]')).toBeNull()
      );
    }
    expect(view.onAnswer).not.toHaveBeenCalled();
    expect(view.removeAttachment).not.toHaveBeenCalled();
    expect(startAudioRecording).not.toHaveBeenCalled();
    view.done();
  });

  it("asks before Replace audio and starts recording only on confirm", async () => {
    const session = { stop: vi.fn(), cancel: vi.fn() };
    const startAudioRecording = vi.fn().mockResolvedValue(session);
    const view = await renderSaved(startAudioRecording);
    await view.press("question-narr_audio");
    await vi.waitFor(() =>
      expect(view.container.querySelector('[data-testid="question-narr_audio-confirm"]')?.textContent).toContain(
        "Record again?"
      )
    );
    expect(startAudioRecording).not.toHaveBeenCalled();
    await view.press("question-narr_audio-confirm-yes");
    await vi.waitFor(() => expect(startAudioRecording).toHaveBeenCalledTimes(1));
    expect(view.removeAttachment).not.toHaveBeenCalled();
    view.done();
  });
});

describe("pausing a recording", () => {
  it("shows Pause / Resume and the time left from the host's state, and the web recorder (no pause) shows neither", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    let paused = false;
    const session = {
      stop: vi.fn(),
      cancel: vi.fn(),
      pause: vi.fn(() => { paused = true; }),
      resume: vi.fn(() => { paused = false; }),
      getState: () => ({ elapsedMs: 65_000, paused, limitMs: 30 * 60_000 })
    };
    const render = (startAudioRecording: () => Promise<unknown>) =>
      root.render(
        <WhoVaQuestionControls.Audio
          question={instrument.questions[0]!}
          value={undefined}
          data={{}}
          locale="en"
          issues={[]}
          platform={{ startAudioRecording: startAudioRecording as never }}
          onAnswer={vi.fn()}
        />
      );
    render(async () => session);
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio"]')?.click();
    await vi.waitFor(() => expect(container.querySelector('[data-testid="question-narr_audio-timer"]')?.textContent).toContain("01:05"));
    expect(container.querySelector('[data-testid="question-narr_audio-timer"]')?.textContent).toContain("28:55 left");
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio-pause"]')?.click();
    await vi.waitFor(() => expect(container.querySelector('[data-testid="question-narr_audio-pause"]')?.textContent).toBe("Resume"));
    expect(session.pause).toHaveBeenCalledTimes(1);
    expect(container.querySelector('[data-testid="question-narr_audio-timer"]')?.textContent).toContain("Paused");
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio-pause"]')?.click();
    await vi.waitFor(() => expect(container.querySelector('[data-testid="question-narr_audio-pause"]')?.textContent).toBe("Pause"));
    expect(session.resume).toHaveBeenCalledTimes(1);
    root.unmount();

    // A recorder that cannot pause: no button, wall-clock timer, no "left".
    const root2 = createRoot(container);
    root2.render(
      <WhoVaQuestionControls.Audio
        question={instrument.questions[0]!}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ startAudioRecording: (async () => ({ stop: vi.fn(), cancel: vi.fn() })) as never }}
        onAnswer={vi.fn()}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[data-testid="question-narr_audio"]')?.click();
    await vi.waitFor(() => expect(container.querySelector('[data-testid="question-narr_audio-timer"]')).not.toBeNull());
    expect(container.querySelector('[data-testid="question-narr_audio-pause"]')).toBeNull();
    expect(container.querySelector('[data-testid="question-narr_audio-timer"]')?.textContent).not.toContain("left");
    root2.unmount();
    container.remove();
  });
});
