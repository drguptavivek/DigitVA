/** @jest-environment jsdom */
import React, { act } from "react";

import { AttachmentGallery } from "../src/workspace/media/AttachmentGallery.web";

// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createRoot } = require("react-dom/client") as { createRoot: (el: Element) => { render(node: React.ReactNode): void; unmount(): void } };

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const imageOne = "/api/v1/attachments/0123456789abcdef0123456789abcdef.jpg";
const items = [{ label: "Document one", value: imageOne, flip: false, info: false }];

function mountOpen() {
  const host = document.createElement("div");
  document.body.appendChild(host);
  const root = createRoot(host);
  act(() => root.render(<AttachmentGallery items={items} label="Documents" />));
  act(() => { (host.querySelector("[aria-label='Open Document one full screen']") as HTMLElement).click(); });
  const dialog = document.querySelector("[role='dialog']") as HTMLElement;
  return { host, root, dialog };
}

function pointer(target: Element, type: string, x: number, y: number) {
  const event = new MouseEvent(type, { bubbles: true, clientX: x, clientY: y });
  Object.defineProperty(event, "pointerId", { value: 1 });
  act(() => { target.dispatchEvent(event); });
}

const zoomText = (dialog: HTMLElement) => dialog.textContent;
const transform = (dialog: HTMLElement) => (dialog.querySelector("img") as HTMLElement).style.transform;

test("the lightbox and its close button mount under document.body, above the workspace stacking context", () => {
  const { host, root, dialog } = mountOpen();
  expect(dialog).not.toBeNull();
  expect(dialog.parentElement).toBe(document.body);
  expect(host.contains(dialog)).toBe(false);
  expect(dialog.querySelector("[aria-label='Close full screen']")).not.toBeNull();
  act(() => { (dialog.querySelector("[aria-label='Close full screen']") as HTMLElement).click(); });
  expect(document.querySelector("[role='dialog']")).toBeNull();
  act(() => root.unmount());
});

test("a native image drag is prevented so pointer panning is not cancelled", () => {
  const { root, dialog } = mountOpen();
  const img = dialog.querySelector("img") as HTMLImageElement;
  expect(img.draggable).toBe(false);
  const event = new Event("dragstart", { bubbles: true, cancelable: true });
  act(() => { img.dispatchEvent(event); });
  expect(event.defaultPrevented).toBe(true);
  act(() => root.unmount());
});

test("wheel zooms with a cancelled page scroll, and a pointer drag at zoom > 1 pans the image", () => {
  const { root, dialog } = mountOpen();
  const viewport = dialog.querySelector("img")!.parentElement as HTMLElement;
  viewport.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 400, right: 400, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });
  const wheel = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -100, clientX: 300, clientY: 200 });
  act(() => { viewport.dispatchEvent(wheel); });
  expect(wheel.defaultPrevented).toBe(true);
  expect(zoomText(dialog)).toContain("125%");
  // Cursor 100px right of centre: the image shifts left so the point under the cursor stays put.
  expect(transform(dialog)).toContain("translate(-25px, 0px)");

  pointer(viewport, "pointerdown", 200, 200);
  pointer(viewport, "pointermove", 230, 220);
  expect(transform(dialog)).toContain("translate(5px, 20px)");
  pointer(viewport, "pointerup", 230, 220);

  const out = new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: 100, clientX: 300, clientY: 200 });
  act(() => { viewport.dispatchEvent(out); });
  expect(zoomText(dialog)).toContain("100%");
  expect(transform(dialog)).toContain("translate(0px, 0px)");
  act(() => root.unmount());
});

test("two wheel events dispatched before any re-render zoom two steps", () => {
  const { root, dialog } = mountOpen();
  const viewport = dialog.querySelector("img")!.parentElement as HTMLElement;
  viewport.getBoundingClientRect = () => ({ left: 0, top: 0, width: 400, height: 400, right: 400, bottom: 400, x: 0, y: 0, toJSON: () => ({}) });
  const wheel = () => new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -100, clientX: 200, clientY: 200 });
  act(() => { viewport.dispatchEvent(wheel()); viewport.dispatchEvent(wheel()); });
  expect(zoomText(dialog)).toContain("150%");
  act(() => root.unmount());
});
