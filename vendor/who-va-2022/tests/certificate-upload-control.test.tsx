// @vitest-environment jsdom
import React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";
import type { InstrumentQuestion } from "../src/index.js";
import { WhoVaQuestionControls } from "../src/web.js";

const certificate: InstrumentQuestion = {
  name: "death_certificate_upload",
  order: 1,
  sourceRow: 1,
  sourceType: "custom-attachment",
  dataType: "attachment",
  control: "file",
  appearance: "image-or-pdf",
  label: { en: "Upload medical certificate (image or PDF)" },
  hint: {},
  guidance: {},
  required: false,
  readOnly: false,
  constraintMessage: {},
  sectionPath: ["consented", "deathcert"]
};

const photo = {
  processed: true,
  mimeType: "image/jpeg",
  id: "cert",
  uri: "data:image/jpeg;base64,/9j/",
  name: "certificate.jpg",
  originalName: "IMG_1.jpg",
  size: 1000,
  width: 800,
  height: 1200
};

async function render(props: Partial<React.ComponentProps<typeof WhoVaQuestionControls.File>>) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const onAnswer = vi.fn();
  root.render(
    <WhoVaQuestionControls.File
      question={certificate}
      value={undefined}
      data={{}}
      locale="en"
      issues={[]}
      onAnswer={onAnswer}
      {...props}
    />
  );
  await new Promise((resolve) => setTimeout(resolve, 0));
  const byTestId = (id: string) => container.querySelector<HTMLElement>(`[data-testid="${id}"]`);
  const done = () => {
    root.unmount();
    container.remove();
  };
  return { container, onAnswer, byTestId, done };
}

describe("medical certificate upload (image or PDF)", () => {
  it("offers Camera and saves the photographed certificate", async () => {
    const captureImage = vi.fn().mockResolvedValue(photo);
    const view = await render({ platform: { captureImage, selectFile: vi.fn() } });
    view.byTestId("question-death_certificate_upload-camera")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(photo));
    view.done();
  });

  it("previews a saved image with the viewer actions, and asks before deleting it", async () => {
    const removeAttachment = vi.fn().mockResolvedValue(undefined);
    const view = await render({ value: photo as never, platform: { removeAttachment, selectFile: vi.fn() } });
    expect(view.byTestId("question-death_certificate_upload-preview")).not.toBeNull();
    for (const label of ["Hide image", "Rotate", "Zoom in", "Zoom out"]) {
      expect(view.container.querySelector(`[aria-label="${label}"]`)).not.toBeNull();
    }
    view.byTestId("question-death_certificate_upload-remove")!.click();
    await vi.waitFor(() => expect(view.byTestId("question-death_certificate_upload-confirm")).not.toBeNull());
    expect(view.onAnswer).not.toHaveBeenCalled();
    view.byTestId("question-death_certificate_upload-confirm-cancel")!.click();
    await vi.waitFor(() => expect(view.byTestId("question-death_certificate_upload-confirm")).toBeNull());
    view.byTestId("question-death_certificate_upload-remove")!.click();
    await vi.waitFor(() => expect(view.byTestId("question-death_certificate_upload-confirm-yes")).not.toBeNull());
    view.byTestId("question-death_certificate_upload-confirm-yes")!.click();
    await vi.waitFor(() => expect(view.onAnswer).toHaveBeenCalledWith(undefined));
    expect(removeAttachment).toHaveBeenCalledWith(expect.objectContaining({ id: "cert" }));
    view.done();
  });
});
