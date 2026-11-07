// @vitest-environment jsdom
/** A resumed draft keeps an image answer as the bare "who-va-attachment:<id>" string. */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";
import { WhoVaQuestionControls } from "../src/web.js";

const imageQuestion: InstrumentQuestion = {
  name: "imagenarr", order: 1, sourceRow: 1, sourceType: "image", dataType: "attachment", control: "image",
  label: { en: "Narrative photo" }, hint: {}, guidance: {}, required: false, readOnly: false,
  constraintMessage: {}, sectionPath: ["narrative"]
};

afterEach(() => document.body.replaceChildren());

function render(platform: Record<string, unknown>) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() => {
    root.render(
      <WhoVaQuestionControls.Image question={imageQuestion} value="who-va-attachment:opaque" data={{}} locale="en"
        issues={[]} onAnswer={() => undefined} platform={platform} />
    );
  });
  return { container, root };
}

it("resolves a bare string answer before previewing it", async () => {
  const resolveAttachmentUri = vi.fn().mockResolvedValue("blob:resolved");
  const { container, root } = render({ resolveAttachmentUri });
  await vi.waitFor(() => expect(resolveAttachmentUri).toHaveBeenCalledWith({ uri: "who-va-attachment:opaque", id: "opaque" }));
  await vi.waitFor(() => expect(container.querySelector("img")?.getAttribute("src")).toBe("blob:resolved"));
  root.unmount();
});

it("never hands an unresolvable opaque ref to the image element", async () => {
  const { container, root } = render({});
  expect(container.querySelector("[data-testid]")).not.toBeNull();
  expect(container.querySelector('img[src^="who-va-attachment:"]')).toBeNull();
  root.unmount();
});
