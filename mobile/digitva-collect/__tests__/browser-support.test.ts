import { outdatedBrowser } from "../src/browserSupport";

// The banner on the web app: iOS Safari < 15.4 / Chrome < 108 lack 100dvh.
afterEach(() => { delete (globalThis as { CSS?: unknown }).CSS; });

test("flags a browser without dynamic viewport units, and not a current one or a native app", () => {
  expect(outdatedBrowser()).toBe(false); // no CSS object: native, or unknown
  (globalThis as { CSS?: unknown }).CSS = { supports: () => false };
  expect(outdatedBrowser()).toBe(true);
  (globalThis as { CSS?: unknown }).CSS = { supports: (property: string, value: string) => property === "height" && value === "100dvh" };
  expect(outdatedBrowser()).toBe(false);
});
