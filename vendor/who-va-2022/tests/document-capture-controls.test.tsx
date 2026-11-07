// @vitest-environment jsdom
/**
 * Document photos (digitva-lq5m): "Scan document" leads on document questions and falls back to the camera, a
 * blurry capture offers a retake without blocking the save, and the recorder shows its state.
 */
import React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";
import { WhoVaQuestionControls } from "../src/web.js";

const base: InstrumentQuestion = {
  name: "imagenarr",
  order: 1,
  sourceRow: 1,
  sourceType: "image",
  dataType: "attachment",
  control: "image",
  label: { en: "Photograph the written narrative" },
  hint: {},
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["narrative"]
};

const raw = { uri: "file:///cache/scan.jpg", name: "scan.jpg", mimeType: "image/jpeg" };
const processed = {
  processed: true as const,
  mimeType: "image/jpeg" as const,
  id: "doc",
  uri: "data:image/jpeg;base64,/9j/",
  name: "doc.jpg",
  originalName: "scan.jpg",
  size: 1000,
  width: 800,
  height: 1200
};

afterEach(() => document.body.replaceChildren());

async function render(element: (onAnswer: (value: unknown) => void) => React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const onAnswer = vi.fn<(value: unknown) => void>();
  root.render(element(onAnswer));
  await new Promise((resolve) => setTimeout(resolve, 0));
  const byTestId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  return { container, root, onAnswer, byTestId };
}

describe("document capture", () => {
  it("leads with Scan document on a document question and saves the scan through processImage", async () => {
    const scanDocument = vi.fn().mockResolvedValue(raw);
    const captureImage = vi.fn();
    const processImage = vi.fn().mockResolvedValue(processed);
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={base}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ scanDocument, captureImage, selectImage: vi.fn(), processImage }}
        onAnswer={onAnswer}
      />
    ));
    const row = view.byTestId("question-imagenarr-scan")!.parentElement!;
    const order = Array.from(row.querySelectorAll("[data-testid]")).map((node) =>
      node.getAttribute("data-testid")
    );
    expect(order).toEqual([
      "question-imagenarr-scan",
      "question-imagenarr-camera",
      "question-imagenarr-library"
    ]);
    expect(view.byTestId("question-imagenarr-scan")!.textContent).toBe("Scan document");

    view.byTestId("question-imagenarr-scan")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    expect(processImage).toHaveBeenCalledWith(raw, expect.anything(), base, {});
    expect(captureImage).not.toHaveBeenCalled();
    view.root.unmount();
  });

  it("falls back to the plain camera when the scanner fails, and not when the interviewer cancels", async () => {
    const scanDocument = vi
      .fn()
      .mockRejectedValueOnce(new Error("no Play services"))
      .mockResolvedValueOnce(undefined);
    const captureImage = vi.fn().mockResolvedValue(raw);
    const processImage = vi.fn().mockResolvedValue(processed);
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "md_im1" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ scanDocument, captureImage, processImage }}
        onAnswer={onAnswer}
      />
    ));
    view.byTestId("question-md_im1-scan")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    expect(captureImage).toHaveBeenCalledTimes(1);

    view.byTestId("question-md_im1-scan")!.click();
    await vi.waitFor(() => expect(scanDocument).toHaveBeenCalledTimes(2));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(captureImage).toHaveBeenCalledTimes(1);
    view.root.unmount();
  });

  it("keeps Camera first on other image questions and on hosts without a scanner", async () => {
    const other = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ scanDocument: vi.fn(), captureImage: vi.fn() }}
        onAnswer={onAnswer}
      />
    ));
    expect(other.byTestId("question-photo-camera")).not.toBeNull();
    expect(other.byTestId("question-photo-scan")).toBeNull();
    other.root.unmount();

    const web = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={base}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ captureImage: vi.fn() }}
        onAnswer={onAnswer}
      />
    ));
    expect(web.byTestId("question-imagenarr-camera")).not.toBeNull();
    expect(web.byTestId("question-imagenarr-scan")).toBeNull();
    web.root.unmount();
  });

  it("offers Scan document first on the image-or-PDF certificate upload", async () => {
    const scanDocument = vi.fn().mockResolvedValue(raw);
    const processImage = vi.fn().mockResolvedValue(processed);
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.File
        question={{
          ...base,
          name: "custom_medical_certificate_upload",
          control: "file",
          appearance: "image-or-pdf"
        }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ scanDocument, captureImage: vi.fn(), selectFile: vi.fn(), processImage }}
        onAnswer={onAnswer}
      />
    ));
    const row = view.byTestId("question-custom_medical_certificate_upload-scan")!.parentElement!;
    const order = Array.from(row.querySelectorAll("[data-testid]")).map((node) =>
      node.getAttribute("data-testid")
    );
    expect(order).toEqual([
      "question-custom_medical_certificate_upload-scan",
      "question-custom_medical_certificate_upload-camera",
      "question-custom_medical_certificate_upload"
    ]);
    view.byTestId("question-custom_medical_certificate_upload-scan")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    view.root.unmount();
  });
});

describe("blur check", () => {
  it("checks the raw capture before processing, saves it, and offers a retake that Keep dismisses", async () => {
    const calls: string[] = [];
    const checkSharpness = vi.fn(async (uri: string) => {
      calls.push(`check ${uri}`);
      return { score: 12, blurry: true };
    });
    const processImage = vi.fn(async () => {
      calls.push("process");
      return processed;
    });
    const removeAttachment = vi.fn();
    const captureImage = vi.fn().mockResolvedValue(raw);
    let value: unknown;
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ captureImage, processImage, checkSharpness, removeAttachment }}
        onAnswer={(next) => {
          value = next;
          onAnswer(next);
        }}
      />
    ));
    view.byTestId("question-photo-camera")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    expect(calls).toEqual(["check file:///cache/scan.jpg", "process"]);

    // The control is controlled: show it the saved value, as the form would.
    view.root.render(
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={value as never}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ captureImage, processImage, checkSharpness, removeAttachment }}
        onAnswer={view.onAnswer}
      />
    );
    await vi.waitFor(() => expect(view.byTestId("question-photo-blurry")).not.toBeNull());
    expect(view.byTestId("question-photo-blurry")!.textContent).toContain("This photo looks blurry. Retake?");
    view.byTestId("question-photo-blurry-cancel")!.click();
    await vi.waitFor(() => expect(view.byTestId("question-photo-blurry")).toBeNull());
    expect(view.onAnswer).toHaveBeenCalledTimes(1);
    expect(removeAttachment).not.toHaveBeenCalled();
    view.root.unmount();
  });

  it("Retake runs the same source again and replaces the blurry photo", async () => {
    const checkSharpness = vi
      .fn()
      .mockResolvedValueOnce({ score: 5, blurry: true })
      .mockResolvedValue({ score: 900, blurry: false });
    const second = { ...processed, id: "doc2" };
    const processImage = vi.fn().mockResolvedValueOnce(processed).mockResolvedValueOnce(second);
    const captureImage = vi.fn().mockResolvedValue(raw);
    const removeAttachment = vi.fn().mockResolvedValue(undefined);
    const platform = { captureImage, processImage, checkSharpness, removeAttachment };
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={platform}
        onAnswer={onAnswer}
      />
    ));
    view.byTestId("question-photo-camera")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    view.root.render(
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={processed as never}
        data={{}}
        locale="en"
        issues={[]}
        platform={platform}
        onAnswer={view.onAnswer}
      />
    );
    await vi.waitFor(() => expect(view.byTestId("question-photo-blurry-yes")).not.toBeNull());
    view.byTestId("question-photo-blurry-yes")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(second));
    expect(captureImage).toHaveBeenCalledTimes(2);
    expect(removeAttachment).toHaveBeenCalledWith(expect.objectContaining({ id: "doc" }));
    await vi.waitFor(() => expect(view.byTestId("question-photo-blurry")).toBeNull());
    view.root.unmount();
  });

  it("a failing sharpness check never blocks the save", async () => {
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Image
        question={{ ...base, name: "photo" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{
          captureImage: vi.fn().mockResolvedValue(raw),
          processImage: vi.fn().mockResolvedValue(processed),
          checkSharpness: vi.fn().mockRejectedValue(new Error("decode failed"))
        }}
        onAnswer={onAnswer}
      />
    ));
    view.byTestId("question-photo-camera")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(processed));
    expect(view.byTestId("question-photo-blurry")).toBeNull();
    view.root.unmount();
  });
});

describe("recorder", () => {
  it("shows the recording state: dot, time, progress toward the limit, Pause beside Stop, Cancel last", async () => {
    const session = {
      stop: vi.fn(),
      cancel: vi.fn(),
      pause: vi.fn(),
      resume: vi.fn(),
      getState: () => ({ elapsedMs: 18 * 60_000, paused: false, limitMs: 30 * 60_000 })
    };
    const view = await render((onAnswer) => (
      <WhoVaQuestionControls.Audio
        question={{ ...base, name: "narr_audio", sourceType: "audio", control: "audio" }}
        value={undefined}
        data={{}}
        locale="en"
        issues={[]}
        platform={{ startAudioRecording: (async () => session) as never }}
        onAnswer={onAnswer}
      />
    ));
    expect(view.byTestId("question-narr_audio")!.textContent).toBe("Record audio");
    expect(view.byTestId("question-narr_audio-progress")).toBeNull();
    view.byTestId("question-narr_audio")!.click();
    await vi.waitFor(() =>
      expect(view.byTestId("question-narr_audio-timer")?.textContent).toContain("18:00")
    );
    expect(view.byTestId("question-narr_audio-timer")!.textContent).toContain("12:00 left");
    const fill = view.byTestId("question-narr_audio-progress")!.firstElementChild as HTMLElement;
    expect(fill.style.width).toBe("60%");
    // Pause and Stop share one row; Cancel is a separate text action after it.
    const row = view.byTestId("question-narr_audio")!.parentElement!;
    expect(Array.from(row.children).map((node) => node.getAttribute("data-testid"))).toEqual([
      "question-narr_audio-pause",
      "question-narr_audio"
    ]);
    expect(view.byTestId("question-narr_audio")!.textContent).toBe("Stop and save recording");
    const cancel = view.byTestId("question-narr_audio-cancel")!;
    expect(cancel.textContent).toBe("Cancel recording");
    expect(row.compareDocumentPosition(cancel) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    cancel.click();
    await vi.waitFor(() => expect(view.byTestId("question-narr_audio-timer")).toBeNull());
    expect(session.cancel).toHaveBeenCalled();
    view.root.unmount();
  });
});
