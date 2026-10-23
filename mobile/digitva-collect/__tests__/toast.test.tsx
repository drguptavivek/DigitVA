import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 20, left: 0, right: 0 }) }));
import { TOAST_ERROR_MS, TOAST_EXPANDED_MS, TOAST_MS, ToastProvider, useToast } from "../src/toast";

let show!: ReturnType<typeof useToast>["show"];
function Probe() {
  show = useToast().show;
  return null;
}
const alerts = (tree: ReactTestRenderer) =>
  tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "alert");
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

let tree: ReactTestRenderer;
beforeEach(async () => {
  jest.useFakeTimers();
  await act(async () => { tree = create(<ToastProvider><Probe /></ToastProvider>); });
});
afterEach(async () => {
  await act(async () => tree.unmount());
  jest.useRealTimers();
});

it("is a no-op without a provider", () => {
  const Lone = () => { useToast().show({ kind: "info", text: "x" }); return null; };
  let lone!: ReactTestRenderer;
  act(() => { lone = create(<Lone />); });
  act(() => lone.unmount());
});

it("hides info and success after 4 s and errors after 6 s", async () => {
  await act(async () => { show({ kind: "info", text: "i" }); show({ kind: "error", text: "e" }); });
  expect(alerts(tree)).toHaveLength(2);
  await act(async () => { jest.advanceTimersByTime(TOAST_MS + 50); });
  expect(text(tree)).not.toContain('"i"');
  expect(text(tree)).toContain("e");
  await act(async () => { jest.advanceTimersByTime(TOAST_ERROR_MS - TOAST_MS + 50); });
  expect(alerts(tree)).toHaveLength(0);
});

it("de-duplicates by text and restarts the timer", async () => {
  await act(async () => { show({ kind: "success", text: "saved" }); });
  await act(async () => { jest.advanceTimersByTime(3_000); });
  await act(async () => { show({ kind: "success", text: "saved" }); });
  expect(alerts(tree)).toHaveLength(1);
  await act(async () => { jest.advanceTimersByTime(3_000); });
  expect(alerts(tree)).toHaveLength(1);
  await act(async () => { jest.advanceTimersByTime(1_100); });
  expect(alerts(tree)).toHaveLength(0);
});

it("stacks at most two, dropping the oldest", async () => {
  await act(async () => { show({ kind: "info", text: "one" }); show({ kind: "info", text: "two" }); show({ kind: "info", text: "three" }); });
  expect(alerts(tree)).toHaveLength(2);
  expect(text(tree)).not.toContain('"one"');
  expect(text(tree)).toContain("three");
});

it("keeps an error's Ref line as detail: tap shows it for 15 s, tap again collapses", async () => {
  await act(async () => { show({ kind: "error", text: "Could not send.\nRef: HTTP 500" }); });
  expect(text(tree)).toContain("Could not send.");
  expect(text(tree)).not.toContain("Ref: HTTP 500");
  await act(async () => { tree.root.findAll((n) => n.props.accessibilityRole === "alert" && typeof n.props.onPress === "function")[0].props.onPress(); });
  expect(text(tree)).toContain("Ref: HTTP 500");
  await act(async () => { jest.advanceTimersByTime(TOAST_ERROR_MS + 100); });
  expect(alerts(tree)).toHaveLength(1);
  await act(async () => { jest.advanceTimersByTime(TOAST_EXPANDED_MS - TOAST_ERROR_MS - 200); });
  expect(alerts(tree)).toHaveLength(1);
  await act(async () => { jest.advanceTimersByTime(200); });
  expect(alerts(tree)).toHaveLength(0);
});

it("is a polite live region that lets touches through around it and sits above the bottom inset", async () => {
  await act(async () => { show({ kind: "info", text: "hello" }); });
  const json = text(tree);
  expect(json).toContain('"accessibilityLiveRegion":"polite"');
  expect(json).toContain('"pointerEvents":"box-none"');
  expect(json).toContain('"bottom":36');
});
