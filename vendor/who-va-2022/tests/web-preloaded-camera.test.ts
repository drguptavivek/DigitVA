// @vitest-environment jsdom
import { expect, it } from "vitest";
import * as preloaded from "../src/web-preloaded.js";

// The Expo web client reads the camera from this entry; a missing export silently falls back to the file picker.
it("web/preloaded exports the live-camera capture", () => {
  expect(typeof preloaded.captureWebCameraPhoto).toBe("function");
});
