import { missingKeyboardSpace } from "../src/keyboardInset";

test("adds the covered height when the window did not shrink (Android 9)", () => {
  expect(missingKeyboardSpace(800, 800, 500)).toBe(300);
});

test("adds nothing when the system already resized the window", () => {
  expect(missingKeyboardSpace(500, 800, 500)).toBe(0);
});

test("adds nothing when the keyboard is off screen", () => {
  expect(missingKeyboardSpace(800, 800, 800)).toBe(0);
});
