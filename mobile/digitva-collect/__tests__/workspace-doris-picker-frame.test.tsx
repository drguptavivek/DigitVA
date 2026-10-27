import React from "react";
import { act, create } from "react-test-renderer";

// Explicit .tsx: the bare name resolves to the native WebView host under jest-expo.
const { IcdPickerFrame } = require("../src/workspace/doris/IcdPickerFrame.tsx") as typeof import("../src/workspace/doris/IcdPickerFrame");

// The real web host (the other DORIS tests mock it): origin and source checks on page messages.
const origin = "https://digitva.test";
const init = { title: "Immediate cause", accent: "#1D4ED8", allowUncoded: true, theme: "light" as const };

function mount(extra: { onClose?: () => void } = {}) {
  const listeners: Array<(event: unknown) => void> = [];
  const frameWindow = { postMessage: jest.fn() };
  const win = globalThis as unknown as { window: unknown };
  const previous = win.window;
  win.window = {
    location: { origin },
    addEventListener: (_type: string, listener: (event: unknown) => void) => listeners.push(listener),
    removeEventListener: (_type: string, listener: (event: unknown) => void) => { listeners.splice(listeners.indexOf(listener), 1); },
  };
  const onMessage = jest.fn();
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(<IcdPickerFrame init={init} revision={4} onMessage={onMessage} onClose={extra.onClose} />, { createNodeMock: () => ({ contentWindow: frameWindow }) });
  });
  const send = (event: { source: unknown; origin: string; data: unknown }) => act(() => listeners.forEach((listener) => listener(event)));
  return { tree, onMessage, frameWindow, send, restore: () => { act(() => tree.unmount()); win.window = previous; } };
}

test("only the iframe's own window at our own origin is heard", () => {
  const { onMessage, frameWindow, send, restore } = mount();
  const data = { t: "select", choice: { code: "CA40", uri: "u" } };
  // Subject present: the frame's own message is accepted.
  send({ source: frameWindow, origin, data });
  expect(onMessage).toHaveBeenCalledTimes(1);
  expect(onMessage.mock.calls[0][0]).toEqual(data);
  // Absent: another window, or the right window at another origin.
  send({ source: { postMessage: jest.fn() }, origin, data });
  send({ source: frameWindow, origin: "https://evil.test", data });
  send({ source: null, origin, data });
  expect(onMessage).toHaveBeenCalledTimes(1);
  restore();
});

test("answers ready with init for the frame's own window only, addressed to our origin", () => {
  const { onMessage, frameWindow, send, restore } = mount();
  send({ source: { postMessage: jest.fn() }, origin, data: { t: "ready" } });
  const initCalls = () => frameWindow.postMessage.mock.calls.filter(([message]) => message.t === "init");
  expect(initCalls()).toHaveLength(0);
  send({ source: frameWindow, origin, data: { t: "ready" } });
  expect(initCalls()).toHaveLength(1);
  expect(initCalls()[0][0]).toMatchObject({ t: "init", title: "Immediate cause", revision: 4 });
  expect(initCalls()[0][1]).toBe(origin);
  expect(onMessage).not.toHaveBeenCalled();
  restore();
});

const initCount = (frameWindow: { postMessage: jest.Mock }) => frameWindow.postMessage.mock.calls.filter(([message]) => message.t === "init").length;

test("a ready posted before the listener existed is lost; the page's repeat is answered", () => {
  const { frameWindow, send, restore } = mount();
  // The first ready had no listener to hear it (nothing was sent); the page repeats it.
  expect(initCount(frameWindow)).toBe(0);
  send({ source: frameWindow, origin, data: { t: "ready" } });
  expect(initCount(frameWindow)).toBe(1);
  restore();
});

test("onLoad pings the page so it re-announces ready", () => {
  const { tree, frameWindow, restore } = mount();
  act(() => tree.root.findByType("iframe").props.onLoad());
  expect(frameWindow.postMessage).toHaveBeenCalledWith({ t: "ping" }, origin);
  restore();
});

test("no ready within the timeout shows Retry, which reloads the frame; a late ready clears the notice", () => {
  jest.useFakeTimers();
  const onClose = jest.fn();
  const { tree, frameWindow, send, restore } = mount({ onClose });
  const frameKey = () => tree.root.findByType("iframe");
  const before = frameKey();
  expect(tree.root.findAllByProps({ role: "alert" })).toHaveLength(0);
  act(() => { jest.advanceTimersByTime(15000); });
  expect(tree.root.findAllByProps({ role: "alert" }).length).toBeGreaterThan(0);
  act(() => tree.root.findByProps({ children: "Close" }).props.onClick());
  expect(onClose).toHaveBeenCalled();
  act(() => tree.root.findByProps({ children: "Retry" }).props.onClick());
  expect(tree.root.findAllByProps({ role: "alert" })).toHaveLength(0);
  expect(frameKey()).not.toBe(before) /* new instance = remounted */;
  // Still no answer: the notice returns; then a late ready recovers without a reload.
  act(() => { jest.advanceTimersByTime(15000); });
  expect(tree.root.findAllByProps({ role: "alert" }).length).toBeGreaterThan(0);
  send({ source: frameWindow, origin, data: { t: "ready" } });
  expect(tree.root.findAllByProps({ role: "alert" })).toHaveLength(0);
  expect(initCount(frameWindow)).toBe(1);
  restore();
  jest.useRealTimers();
});

test("ready before the timeout keeps the notice away", () => {
  jest.useFakeTimers();
  const { tree, frameWindow, send, restore } = mount();
  send({ source: frameWindow, origin, data: { t: "ready" } });
  act(() => { jest.advanceTimersByTime(60000); });
  expect(tree.root.findAllByProps({ role: "alert" })).toHaveLength(0);
  restore();
  jest.useRealTimers();
});
