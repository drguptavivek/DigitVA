// @vitest-environment jsdom

import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";
import { WebAudioPlayer, WhoVaQuestionControls } from "../src/web.js";

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

describe("web audio player", () => {
  it("renders native controls for a saved recording without autoplay", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(
      <WhoVaQuestionControls.Audio
        question={audioQuestion}
        value={{
          id: "audio-1",
          uri: "blob:recording",
          name: "recording.webm",
          originalName: "recording.webm",
          mimeType: "audio/webm",
          size: 1,
          durationMs: 1,
          processed: true
        }}
        data={{}}
        locale="en"
        issues={[]}
        onAnswer={() => undefined}
      />
    );

    const audio = await new Promise<HTMLAudioElement>((resolve) => {
      const find = () => {
        const element = container.querySelector("audio");
        if (element) resolve(element);
        else globalThis.setTimeout(find, 0);
      };
      find();
    });

    expect(audio.controls).toBe(true);
    expect(audio.preload).toBe("metadata");
    expect(audio.src).toContain("blob:recording");
    expect(audio.getAttribute("aria-label")).toBe("Recorded");
    expect(audio.autoplay).toBe(false);
    expect(audio.hasAttribute("autoplay")).toBe(false);
    expect(audio.style.width).toBe("100%");
    expect(audio.style.maxWidth).toBe("640px");
    root.unmount();
  });

  it("exposes the native player primitive for reusable web hosts", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(
      <WebAudioPlayer uri="blob:standalone" accessibilityLabel="Saved audio" onError={() => undefined} />
    );
    await vi.waitFor(() => expect(container.querySelector("audio")).not.toBeNull());
    const audio = container.querySelector("audio");
    expect(audio).not.toBeNull();
    expect(audio?.getAttribute("aria-label")).toBe("Saved audio");
    expect(audio?.src).toContain("blob:standalone");
    root.unmount();
  });
});
