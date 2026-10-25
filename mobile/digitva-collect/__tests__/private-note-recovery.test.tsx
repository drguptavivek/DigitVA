import React from "react";
import { Platform } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
jest.mock("../src/ui", () => {
  const React = require("react") as typeof import("react");
  const { Pressable, Text } = require("react-native") as typeof import("react-native");
  return { Button: ({ label, onPress }: any) => React.createElement(Pressable, { accessibilityLabel: label, onPress }, React.createElement(Text, null, label)), errorText: (error: Error) => error.message, useUiStyles: () => ({}) };
});
const mockStore = new Map<string, string>();
jest.mock("../src/workspace/viewState", () => ({ browserSessionStore: () => ({
  getItem: (key: string) => mockStore.get(key) ?? null,
  setItem: (key: string, value: string) => mockStore.set(key, value),
  removeItem: (key: string) => mockStore.delete(key),
}) }));
import { PrivateNotePanel } from "../src/workspace/PrivateNotePanel";
import { activateBrowserDraft, clearBrowserDraft, readPendingNote } from "../src/workspace/doris/browserDraft";
import type { WorkspaceApi } from "../src/workspace/api";
const context = { fingerprint: "actor-context", vaSid: "case1", mode: "coding", payloadVersion: "payload1", projectMode: "unmasked_doris" };
const identity = { vaSid: "case1", mode: "coding" as const };
const note = { va_sid: "case1", content: "Server saved note", updated_at: null };
const api = { getNote: jest.fn(async () => note), saveNote: jest.fn(async () => note) } as unknown as WorkspaceApi;
let platform: PropertyDescriptor | undefined;
beforeEach(() => {
  platform = Object.getOwnPropertyDescriptor(Platform, "OS");
  Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
  clearBrowserDraft(); mockStore.clear(); activateBrowserDraft(context); jest.clearAllMocks();
});
afterEach(() => { clearBrowserDraft(); if (platform) Object.defineProperty(Platform, "OS", platform); });
async function mount() {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<PrivateNotePanel identity={identity} draftContext={context} api={api} onAllocationLost={jest.fn()} />); });
  return tree;
}
function input(tree: ReactTestRenderer) { return tree.root.findByProps({ accessibilityLabel: "Private note" }); }

test("pending note survives drawer unmount and reload, while saved note is still fetched", async () => {
  const first = await mount();
  expect(input(first).props.value).toBe("Server saved note");
  await act(async () => input(first).props.onChangeText("Unsaved note"));
  await act(async () => first.unmount());
  const second = await mount();
  expect(api.getNote).toHaveBeenCalledTimes(2);
  expect(input(second).props.value).toBe("Unsaved note");
  await act(async () => second.unmount());
});

test("failed save retains pending text and successful save clears only the pending note", async () => {
  const tree = await mount();
  await act(async () => input(tree).props.onChangeText("Retry this note"));
  (api.saveNote as jest.Mock).mockRejectedValueOnce(new Error("Network interrupted"));
  await act(async () => tree.root.findByProps({ accessibilityLabel: "Save private note" }).props.onPress());
  expect(readPendingNote(context)).toBe("Retry this note");
  expect(input(tree).props.value).toBe("Retry this note");
  (api.saveNote as jest.Mock).mockResolvedValueOnce({ ...note, content: "Retry this note" });
  await act(async () => tree.root.findByProps({ accessibilityLabel: "Save private note" }).props.onPress());
  expect(readPendingNote(context)).toBeUndefined();
  expect(input(tree).props.value).toBe("Retry this note");
  await act(async () => tree.unmount());
});

test("a slow save does not discard text typed while it was in flight", async () => {
  const tree = await mount();
  await act(async () => input(tree).props.onChangeText("First edit"));
  let complete!: (value: typeof note) => void;
  (api.saveNote as jest.Mock).mockImplementationOnce(() => new Promise((resolve) => { complete = resolve; }));
  await act(async () => tree.root.findByProps({ accessibilityLabel: "Save private note" }).props.onPress());
  await act(async () => input(tree).props.onChangeText("Later unsaved edit"));
  await act(async () => complete({ ...note, content: "First edit" }));
  expect(input(tree).props.value).toBe("Later unsaved edit");
  expect(readPendingNote(context)).toBe("Later unsaved edit");
  await act(async () => tree.unmount());
});
