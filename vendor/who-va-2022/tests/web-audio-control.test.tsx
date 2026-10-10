// @vitest-environment jsdom

import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AttachmentReference, InstrumentQuestion } from "../src/index.js";
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

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.replaceChildren();
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function renderAudio(
  container: HTMLElement,
  props: Partial<React.ComponentProps<typeof WhoVaQuestionControls.Audio>> = {}
) {
  const root = createRoot(container);
  root.render(
    <WhoVaQuestionControls.Audio
      question={audioQuestion}
      value={undefined}
      data={{}}
      locale="en"
      issues={[]}
      onAnswer={() => undefined}
      {...props}
    />
  );
  return root;
}

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

  it("resolves saved playback and releases a URI when the answer changes", async () => {
    const resolution = deferred<string | undefined>();
    const releaseAttachmentUri = vi.fn();
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    root.render(
      <WhoVaQuestionControls.Audio
        question={audioQuestion}
        value={{ uri: "who-va-attachment:saved", id: "saved", mimeType: "audio/webm" }}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ resolveAttachmentUri: vi.fn(() => resolution.promise), releaseAttachmentUri }}
        onAnswer={onAnswer}
      />
    );
    await vi.waitFor(() => expect(container.textContent).toContain("Loading recording"));
    root.render(
      <WhoVaQuestionControls.Audio
        question={audioQuestion}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ resolveAttachmentUri: vi.fn(() => resolution.promise), releaseAttachmentUri }}
        onAnswer={onAnswer}
      />
    );
    await new Promise((resolve) => setTimeout(resolve, 0));
    resolution.resolve("blob:saved");
    await vi.waitFor(() => expect(releaseAttachmentUri).toHaveBeenCalledWith("blob:saved"));
    expect(container.querySelector("audio")).toBeNull();
    root.unmount();
  });

  it("normalizes an opaque string answer before resolving saved playback", async () => {
    const resolveAttachmentUri = vi.fn().mockResolvedValue("blob:resolved");
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: "who-va-attachment:opaque",
      platform: { resolveAttachmentUri }
    });
    await vi.waitFor(() =>
      expect(resolveAttachmentUri).toHaveBeenCalledWith({
        uri: "who-va-attachment:opaque",
        id: "opaque"
      })
    );
    await vi.waitFor(() => expect(container.querySelector("audio")?.src).toContain("blob:resolved"));
    root.unmount();
  });

  it("preserves the old answer when recording is cancelled", async () => {
    const oldAnswer: AttachmentReference = { uri: "blob:old", id: "old", mimeType: "audio/webm" };
    const cancel = vi.fn();
    const startAudioRecording = vi.fn().mockResolvedValue({ stop: vi.fn(), cancel });
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, { value: oldAnswer, platform: { startAudioRecording }, onAnswer });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[data-testid="question-narrative_audio-cancel"]')?.click();
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
    expect(onAnswer).not.toHaveBeenCalled();
    expect(container.querySelector("audio")?.getAttribute("src")).toContain("blob:old");
    root.unmount();
  });

  it("does not offer cancellation for legacy captureAudio", async () => {
    const capture = deferred<AttachmentReference>();
    const recorded: AttachmentReference = {
      uri: "who-va-attachment:captured",
      id: "captured",
      mimeType: "audio/webm"
    };
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      platform: { captureAudio: vi.fn(() => capture.promise) },
      onAnswer
    });
    await vi.waitFor(() => expect(container.querySelector('[role="button"]')).not.toBeNull());
    await act(async () => {
      container.querySelector<HTMLElement>('[role="button"]')?.click();
    });
    expect(container.querySelector('[data-testid="question-narrative_audio-cancel"]')).toBeNull();
    capture.resolve(recorded);
    await vi.waitFor(() => expect(onAnswer).toHaveBeenCalledWith(recorded));
    root.unmount();
  });

  it("cancels a failed stop and leaves the old answer in place", async () => {
    const oldAnswer: AttachmentReference = { uri: "blob:old", id: "old", mimeType: "audio/webm" };
    const cancel = vi.fn();
    const stop = vi.fn().mockRejectedValue(new Error("stop failed"));
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: oldAnswer,
      platform: { startAudioRecording: vi.fn().mockResolvedValue({ stop, cancel }) },
      onAnswer
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("Audio recording failed")
    );
    expect(onAnswer).not.toHaveBeenCalled();
    expect(container.querySelector("audio")?.getAttribute("src")).toContain("blob:old");
    root.unmount();
  });

  it("preserves the old answer when starting fails", async () => {
    const oldAnswer: AttachmentReference = { uri: "blob:old", id: "old", mimeType: "audio/webm" };
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: oldAnswer,
      platform: { startAudioRecording: vi.fn().mockRejectedValue(new Error("start failed")) },
      onAnswer
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("Audio recording failed")
    );
    expect(onAnswer).not.toHaveBeenCalled();
    expect(container.querySelector("audio")?.getAttribute("src")).toContain("blob:old");
    root.unmount();
  });

  it("reports a mounted cancellation failure without changing the old answer", async () => {
    const oldAnswer: AttachmentReference = { uri: "blob:old", id: "old", mimeType: "audio/webm" };
    const cancel = vi.fn().mockRejectedValue(new Error("cancel failed"));
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: oldAnswer,
      platform: { startAudioRecording: vi.fn().mockResolvedValue({ stop: vi.fn(), cancel }) },
      onAnswer
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[data-testid="question-narrative_audio-cancel"]')?.click();
    await vi.waitFor(() =>
      expect(container.querySelector('[role="alert"]')?.textContent).toContain("Audio recording failed")
    );
    expect(onAnswer).not.toHaveBeenCalled();
    expect(container.querySelector("audio")?.getAttribute("src")).toContain("blob:old");
    root.unmount();
  });

  it("removes a late stop result without removing the old answer", async () => {
    const oldAnswer: AttachmentReference = {
      uri: "who-va-attachment:old",
      id: "old",
      mimeType: "audio/webm"
    };
    const recorded: AttachmentReference = { uri: "who-va-attachment:new", id: "new", mimeType: "audio/webm" };
    const stopping = deferred<AttachmentReference>();
    const removeAttachment = vi.fn().mockResolvedValue(undefined);
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: oldAnswer,
      platform: {
        startAudioRecording: vi.fn().mockResolvedValue({ stop: () => stopping.promise, cancel: vi.fn() }),
        removeAttachment
      },
      onAnswer
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    root.unmount();
    stopping.resolve(recorded);
    await vi.waitFor(() => expect(removeAttachment).toHaveBeenCalledWith(recorded));
    expect(removeAttachment).not.toHaveBeenCalledWith(oldAnswer);
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("shows elapsed recording time with its label", async () => {
    vi.useFakeTimers();
    const now = vi.spyOn(globalThis.Date, "now").mockReturnValue(1_000);
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      platform: { startAudioRecording: vi.fn().mockResolvedValue({ stop: vi.fn(), cancel: vi.fn() }) }
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      container.querySelector<HTMLElement>('[role="button"]')?.click();
    });
    await vi.waitFor(() => expect(container.textContent).toContain("Recording time 00:00"));
    now.mockReturnValue(61_000);
    await act(async () => {
      vi.advanceTimersByTime(1_000);
    });
    await vi.waitFor(() => expect(container.textContent).toContain("Recording time 01:00"));
    root.unmount();
  });

  it("saves a replacement even when old attachment cleanup fails", async () => {
    const oldAnswer: AttachmentReference = {
      uri: "who-va-attachment:old",
      id: "old",
      mimeType: "audio/webm"
    };
    const recorded: AttachmentReference = { uri: "who-va-attachment:new", id: "new", mimeType: "audio/webm" };
    const removeAttachment = vi.fn(() => {
      throw new Error("cleanup failed");
    });
    const stop = vi.fn().mockResolvedValue(recorded);
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, {
      value: oldAnswer,
      platform: {
        startAudioRecording: vi.fn().mockResolvedValue({ stop, cancel: vi.fn() }),
        removeAttachment,
        resolveAttachmentUri: vi.fn().mockResolvedValue("blob:old")
      },
      onAnswer
    });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(onAnswer).toHaveBeenCalledWith(recorded));
    expect(container.querySelector('[role="alert"]')).toBeNull();
    expect(removeAttachment).toHaveBeenCalledWith(oldAnswer);
    root.unmount();
  });

  it("cancels a session that resolves after unmount", async () => {
    const starting = deferred<{ stop: () => Promise<AttachmentReference>; cancel: () => void }>();
    const cancel = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = renderAudio(container, { platform: { startAudioRecording: vi.fn(() => starting.promise) } });
    await new Promise((resolve) => setTimeout(resolve, 0));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    root.unmount();
    starting.resolve({ stop: vi.fn(), cancel });
    await vi.waitFor(() => expect(cancel).toHaveBeenCalledOnce());
  });

  it("still saves under React StrictMode", async () => {
    const recorded: AttachmentReference = {
      uri: "who-va-attachment:strict",
      id: "strict",
      mimeType: "audio/webm"
    };
    const stop = vi.fn().mockResolvedValue(recorded);
    const onAnswer = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        <React.StrictMode>
          <WhoVaQuestionControls.Audio
            question={audioQuestion}
            value={undefined}
            data={{}}
            locale="en"
            issues={[]}
            platform={{ startAudioRecording: vi.fn().mockResolvedValue({ stop, cancel: vi.fn() }) }}
            onAnswer={onAnswer}
          />
        </React.StrictMode>
      );
    });
    await act(async () => {
      container.querySelector<HTMLElement>('[role="button"]')?.click();
    });
    await vi.waitFor(() => expect(container.textContent).toContain("Stop and save recording"));
    container.querySelector<HTMLElement>('[role="button"]')?.click();
    await vi.waitFor(() => expect(onAnswer).toHaveBeenCalledWith(recorded));
    root.unmount();
  });
});
