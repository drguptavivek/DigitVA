/** Clock notices use only the selected account's server, never a retained enrolment in standalone. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockServer: string | undefined;
const mockRecheck = jest.fn(async (_server: string) => true);
const mockClock = { offsetSeconds: 20_000, measuredAt: 1 };
jest.mock("expo-intent-launcher", () => ({ startActivityAsync: jest.fn(), ActivityAction: { DATE_SETTINGS: "date-settings" } }));
jest.mock("react-native-safe-area-context", () => ({ SafeAreaView: "SafeAreaView", useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ server: mockServer }) }));
jest.mock("../src/phoneClock", () => ({
  usePhoneClock: () => ({ clock: mockClock, level: "block" }),
  recheckPhoneClock: (server: string) => mockRecheck(server),
}));

import { ClockBlock, ClockWarning } from "../src/nativeShell/ClockNotice.native";
import en from "../src/strings/en.json";

let tree: ReactTestRenderer;
beforeEach(() => {
  jest.clearAllMocks();
  mockServer = undefined;
});
afterEach(() => act(() => tree.unmount()));

it.each([ClockWarning, ClockBlock])("hides %p when no selected server account exists despite a retained blocking offset", (Notice) => {
  act(() => { tree = create(<Notice />); });
  expect(tree.toJSON()).toBeNull();
  expect(mockRecheck).not.toHaveBeenCalled();
  expect(mockClock.offsetSeconds).toBe(20_000);
});

it.each(["https://active.example.org", "https://demo.example.org"])("rechecks the selected account's server %s only after the button is pressed", async (server) => {
  mockServer = server;
  await act(async () => { tree = create(<ClockWarning />); });
  expect(tree.toJSON()).not.toBeNull();
  expect(mockRecheck).not.toHaveBeenCalled();
  const button = tree.root.findAll((node) => node.props.accessibilityLabel === en.clockRecheck && typeof node.props.onPress === "function")[0];
  expect(button).toBeDefined();
  await act(async () => { button.props.onPress(); });
  expect(mockRecheck).toHaveBeenCalledWith(server);
});
