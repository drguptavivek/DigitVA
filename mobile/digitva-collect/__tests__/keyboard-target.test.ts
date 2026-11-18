import { isKeyboardTarget } from "../src/web/AppHeader.web";

// The phone tab bar hides while a text field has focus (iOS Safari does not always shrink the visual viewport).
const element = (tagName: string, extra: Record<string, unknown> = {}) => ({ tagName, ...extra }) as unknown as Element;

test("text fields raise the keyboard; buttons, choices and plain elements do not", () => {
  expect(isKeyboardTarget(element("INPUT", { type: "text" }))).toBe(true);
  expect(isKeyboardTarget(element("INPUT", { type: "number" }))).toBe(true);
  expect(isKeyboardTarget(element("TEXTAREA"))).toBe(true);
  expect(isKeyboardTarget(element("DIV", { isContentEditable: true }))).toBe(true);
  expect(isKeyboardTarget(element("INPUT", { type: "radio" }))).toBe(false);
  expect(isKeyboardTarget(element("INPUT", { type: "checkbox" }))).toBe(false);
  expect(isKeyboardTarget(element("BUTTON"))).toBe(false);
  expect(isKeyboardTarget(null)).toBe(false);
});
