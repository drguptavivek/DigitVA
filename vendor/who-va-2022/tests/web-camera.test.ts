// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import { captureWebCameraPhoto } from "../src/web-camera.js";

function mockCamera() {
  const stop = vi.fn();
  const getUserMedia = vi.fn().mockResolvedValue({ getTracks: () => [{ stop }, { stop }] });
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  return { stop, getUserMedia };
}
const buttons = () => [...document.querySelectorAll<HTMLButtonElement>("[role=dialog] button")];

afterEach(() => {
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
  document.body.innerHTML = "";
  vi.restoreAllMocks();
});

describe("captureWebCameraPhoto", () => {
  it("returns a JPEG file on capture and stops every track", async () => {
    const { stop } = mockCamera();
    HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue({ drawImage: vi.fn() }) as never;
    HTMLCanvasElement.prototype.toBlob = ((cb: BlobCallback) => cb(new Blob(["x"], { type: "image/jpeg" }))) as never;
    const result = captureWebCameraPhoto();
    await vi.waitFor(() => expect(buttons()).toHaveLength(2));
    expect(document.activeElement).toBe(buttons()[0]);
    buttons()[0]!.click();
    const file = await result;
    expect(file).toBeInstanceOf(File);
    expect(file?.type).toBe("image/jpeg");
    expect(stop).toHaveBeenCalledTimes(2);
    expect(document.querySelector("[role=dialog]")).toBeNull();
  });

  it("cancels on Escape and on the Cancel button, stopping tracks", async () => {
    const { stop } = mockCamera();
    const first = captureWebCameraPhoto();
    await vi.waitFor(() => expect(buttons()).toHaveLength(2));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(await first).toBeUndefined();
    const second = captureWebCameraPhoto();
    await vi.waitFor(() => expect(buttons()).toHaveLength(2));
    buttons()[1]!.click();
    expect(await second).toBeUndefined();
    expect(stop).toHaveBeenCalledTimes(4);
  });

  it("returns null so the caller falls back when permission is denied or mediaDevices is missing", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true
    });
    expect(await captureWebCameraPhoto()).toBeNull();
    Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
    expect(await captureWebCameraPhoto()).toBeNull();
  });
});
