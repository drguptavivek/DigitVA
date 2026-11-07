// @vitest-environment jsdom
/** The native <Image> must never be given an unresolved "who-va-attachment:" URI, on any render (digitva-961u). */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";

import type { InstrumentQuestion } from "../src/index.js";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const imageUris: Array<string | undefined> = [];

vi.mock("react-native", () => {
  const view = (tag: "div" | "button") =>
    React.forwardRef<HTMLElement, Record<string, unknown>>(({ children, onPress, testID }, ref) =>
      React.createElement(tag, { ref, "data-testid": testID, onClick: onPress as never }, children as React.ReactNode)
    );
  const Image = ({ source }: { source?: { uri?: string } }) => {
    imageUris.push(source?.uri);
    return React.createElement("img");
  };
  return {
    Platform: { OS: "ios" },
    Image,
    Modal: view("div"),
    Pressable: view("button"),
    ScrollView: view("div"),
    Text: view("div"),
    TextInput: view("div"),
    View: view("div")
  };
});

vi.mock("react-native-svg", () => {
  const svg = () => null;
  return { Circle: svg, default: svg, Path: svg };
});

import { WhoVaQuestionControls } from "../src/native.js";

const question: InstrumentQuestion = {
  name: "imagenarr", order: 1, sourceRow: 1, sourceType: "image", dataType: "attachment", control: "image",
  label: { en: "Narrative photo" }, hint: {}, guidance: {}, required: false, readOnly: false,
  constraintMessage: {}, sectionPath: ["narrative"]
};

async function render(platform: Record<string, unknown>) {
  imageUris.length = 0;
  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(
      <WhoVaQuestionControls.Image question={question} value="who-va-attachment:opaque" data={{}} locale="en"
        issues={[]} onAnswer={() => undefined} platform={platform} />
    );
  });
  return root;
}

it("previews only the resolved URI of a resumed draft, never the opaque ref", async () => {
  const resolveAttachmentUri = vi.fn().mockResolvedValue("file:///cache/photo.jpg");
  const root = await render({ resolveAttachmentUri });
  await vi.waitFor(() => expect(imageUris).toContain("file:///cache/photo.jpg"));
  expect(imageUris.filter((uri) => uri?.startsWith("who-va-attachment:"))).toEqual([]);
  root.unmount();
});

it("shows no image at all when the host cannot resolve the ref", async () => {
  const root = await render({});
  expect(imageUris).toEqual([]);
  root.unmount();
});
