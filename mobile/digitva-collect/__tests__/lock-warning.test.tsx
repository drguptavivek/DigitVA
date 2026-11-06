import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

let mockState: { lockWarning?: boolean; activity: jest.Mock };
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ header: true }) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 0, left: 0, right: 0 }) }));

import { LockWarning } from "../src/nativeShell/LockWarning";

let tree: ReactTestRenderer;
const render = async () => { await act(async () => { tree = create(<LockWarning />); }); };
const shown = () => tree.root.findAllByType(Text).map((n) => [n.props.children].flat().join("")).join("|");
afterEach(async () => { await act(async () => tree?.unmount()); });

it("shows nothing until the auto-lock warns", async () => {
  mockState = { lockWarning: false, activity: jest.fn() };
  await render();
  expect(tree.toJSON()).toBeNull();
});

it("says the phone locks in 30 seconds, and Stay unlocked restarts the timer", async () => {
  mockState = { lockWarning: true, activity: jest.fn() };
  await render();
  expect(tree.root.findAllByProps({ testID: "lock-warning" }).length).toBeGreaterThan(0);
  expect(shown()).toContain("This phone locks in 30 seconds.");
  const stay = tree.root.findAll((n) => n.props.accessibilityLabel === "Stay unlocked" && typeof n.props.onPress === "function")[0];
  expect(stay).toBeDefined();
  await act(async () => stay.props.onPress());
  expect(mockState.activity).toHaveBeenCalledTimes(1);
});
