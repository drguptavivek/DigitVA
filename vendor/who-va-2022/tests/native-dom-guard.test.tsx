// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { domElement, focusDomQuestion } from "../src/ui/dom-element.js";
import { focusableWithin, keepInView } from "../src/ui/section-navigation.js";

// React Native 0.86 defines a global HTMLElement (its ReactNativeElement); a
// native view ref passes `instanceof HTMLElement` but has no DOM methods.
class FakeNativeElement {
  measure = vi.fn();
}
const realHTMLElement = globalThis.HTMLElement;
const asNative = () => {
  vi.stubGlobal("HTMLElement", FakeNativeElement);
  return new FakeNativeElement();
};

afterEach(() => {
  vi.unstubAllGlobals();
  expect(globalThis.HTMLElement).toBe(realHTMLElement);
});

describe("native view refs are not DOM elements", () => {
  it("domElement refuses a native ref even though instanceof HTMLElement is true", () => {
    const native = asNative();
    expect(native instanceof HTMLElement).toBe(true);
    expect(domElement(native)).toBeUndefined();
    expect(domElement(null)).toBeUndefined();
    expect(domElement(undefined)).toBeUndefined();
  });

  it("focusDomQuestion leaves a native ref to the platform (returns false, throws nothing)", () => {
    expect(focusDomQuestion(asNative())).toBe(false);
  });

  it("focusableWithin returns nothing for a native ref", () => {
    expect(focusableWithin(asNative())).toEqual([]);
  });

  it("keepInView does nothing for native refs", () => {
    const box = Object.assign(asNative(), { scrollTo: vi.fn(), scrollTop: 0, offsetTop: 0, clientHeight: 10 });
    const item = Object.assign(asNative(), { offsetTop: 100, offsetHeight: 20 });
    expect(() => keepInView(box, item)).not.toThrow();
    expect(box.scrollTo).not.toHaveBeenCalled();
    // A native ref that has scrollTo but no querySelector is still not a DOM element.
    expect(() => keepInView(asNative(), asNative())).not.toThrow();
  });
});

describe("real DOM elements still work", () => {
  it("focusDomQuestion focuses the first control", () => {
    const question = document.createElement("div");
    const input = document.createElement("input");
    question.append(input);
    document.body.append(question);
    expect(focusDomQuestion(question)).toBe(true);
    expect(document.activeElement).toBe(input);
    question.remove();
  });

  it("focusableWithin lists the buttons and inputs of a panel", () => {
    const panel = document.createElement("div");
    panel.innerHTML = '<button id="a"></button><span></span><input id="b" />';
    expect(focusableWithin(panel).map((node) => node.id)).toEqual(["a", "b"]);
  });

  it("keepInView scrolls the box to an item below its visible area", () => {
    const box = document.createElement("div");
    const item = document.createElement("div");
    const scrollTo = vi.fn();
    Object.assign(box, { scrollTo });
    Object.defineProperty(box, "clientHeight", { value: 100 });
    Object.defineProperty(item, "offsetTop", { value: 300 });
    Object.defineProperty(item, "offsetHeight", { value: 20 });
    keepInView(box, item);
    expect(scrollTo).toHaveBeenCalledWith({ top: 228 });
  });
});
