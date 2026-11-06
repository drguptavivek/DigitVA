/** Set PIN: a "too short" error clears as soon as either PIN group changes. */
import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useLocalSearchParams: () => ({ userId: "u1" }),
  useRouter: () => ({ replace: jest.fn() }),
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [{ user_id: "u1", name: "A" }], unlocked: jest.fn() }) }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/interviewerDb", () => ({ createInterviewerDb: jest.fn() }));
jest.mock("../src/standalone/home", () => ({ homeRoute: () => "/" }));
jest.mock("../src/UnlockOffer", () => ({ pendingUnlockOffer: jest.fn(), UnlockOffer: () => null }));
jest.mock("../src/vault", () => ({ pinProblem: () => "pinTooShort", recordPinLength: jest.fn() }));
jest.mock("../src/PinBoxes", () => ({ PinBoxes: () => null }));
jest.mock("../src/ui", () => {
  const { Text } = require("react-native");
  return {
    // The petrol notice as a plain text (an alert for error and warning, as the real one), so the message assertions keep reading its words.
    Notice: ({ children, testID, tone }: { children: React.ReactNode; testID?: string; tone?: string }) =>
      (jest.requireActual("react") as typeof import("react")).createElement((require("react-native") as typeof import("react-native")).Text, { accessibilityRole: tone === "error" || tone === "warning" ? "alert" : undefined, testID }, children),
    useUiStyles: () => ({ muted: {}, text: {}, error: {} }),
    Screen: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Button: ({ label }: { label: string }) => <Text>{label}</Text>,
  };
});

import PinSetup from "../src/nativeRoutes/pin-setup";

const errorTexts = (tree: ReturnType<typeof create>) =>
  tree.root.findAll((n) => n.props.children === "pinTooShort");

it("clears the PIN error when the PIN or Confirm value changes", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<PinSetup />); });
  const [pinBoxes, confirmBoxes] = tree.root.findAllByType(require("../src/PinBoxes").PinBoxes);
  await act(async () => { pinBoxes.props.onChange("123"); confirmBoxes.props.onChange("123"); });
  await act(async () => { tree.root.findByProps({ label: "pinSave" }).props.onPress(); });
  expect(errorTexts(tree).length).toBeGreaterThan(0);
  await act(async () => { pinBoxes.props.onChange("1234"); });
  expect(errorTexts(tree)).toHaveLength(0);
  await act(async () => { tree.root.findByProps({ label: "pinSave" }).props.onPress(); });
  expect(errorTexts(tree).length).toBeGreaterThan(0);
  await act(async () => { confirmBoxes.props.onChange("1234"); });
  expect(errorTexts(tree)).toHaveLength(0);
});
