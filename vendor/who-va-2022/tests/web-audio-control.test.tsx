// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";
import { WhoVaQuestionControls } from "../src/web.js";

const audioQuestion: InstrumentQuestion = {
  name: "narrative_audio",
  order: 1,
  sourceRow: 1,
  sourceType: "audio",
  dataType: "attachment",
  control: "audio",
  label: { en: "Narrative recording" },
  hint: {},
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["narrative"]
};

afterEach(() => document.body.replaceChildren());

describe("web audio control", () => {
  it("changes from start to stop and returns the saved recording", async () => {
    const recorded = { uri: "who-va-attachment:audio-id", id: "audio-id", mimeType: "audio/webm" };
    const stop = vi.fn().mockResolvedValue(recorded);
    const cancel = vi.fn();
    const startAudioRecording = vi.fn().mockResolvedValue({ stop, cancel });
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(
      <WhoVaQuestionControls.Audio
        question={audioQuestion}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ startAudioRecording }}
        onAnswer={onAnswer}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[role="button"]')?.click();

    await vi.waitFor(() => expect(onAnswer).toHaveBeenCalledWith(recorded));
    expect(stop).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("Record audio");
    root.unmount();
  });

  it("shows a useful error when microphone permission is denied", async () => {
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(
      <WhoVaQuestionControls.Audio
        question={audioQuestion}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{
          startAudioRecording: vi.fn().mockRejectedValue(new DOMException("Denied", "NotAllowedError"))
        }}
        onAnswer={onAnswer}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));

    container.querySelector<HTMLElement>('[role="button"]')?.click();

    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain(
        "Microphone permission was denied"
      )
    );
    expect(onAnswer).not.toHaveBeenCalled();
    root.unmount();
  });
});
