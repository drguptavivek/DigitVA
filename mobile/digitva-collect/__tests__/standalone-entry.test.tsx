/** The standalone entry on /enrol is offered on Collect Plus (Android or iOS) only, and only while Active is chosen. */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";
import { Platform, TextInput } from "react-native";

const mockPlus = { value: true };
const mockSlot = { value: "active" as "active" | "demo" | undefined };
const mockStandaloneAvailable = { value: true };
jest.mock("expo-router", () => ({ useRouter: () => ({ replace: jest.fn(), push: jest.fn() }) }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Pixel", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ useCameraPermissions: () => [{ granted: true }, jest.fn()], CameraView: "CameraView" }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: jest.fn(), slot: mockSlot.value, standaloneAvailable: mockStandaloneAvailable.value }) }));
jest.mock("../src/auth", () => ({ redeemSignInQr: jest.fn(), enrolDevice: jest.fn() }));
jest.mock("../src/api", () => ({ ApiError: class extends Error {} }));
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus.value }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      R.createElement("button", { "data-label": label, onClick: onPress, disabled }, label),
    Screen: ({ children }: { children: ReactNode }) => R.createElement("main", null, children),
    errorText: () => "error",
    // The petrol notice as a plain text (an alert for error and warning, as the real one), so the message assertions keep reading its words.
    Notice: ({ children, testID, tone }: { children: React.ReactNode; testID?: string; tone?: string }) =>
      (jest.requireActual("react") as typeof import("react")).createElement((require("react-native") as typeof import("react-native")).Text, { accessibilityRole: tone === "error" || tone === "warning" ? "alert" : undefined, testID }, children),
    SegmentedControl: ({ options, onChange, disabled }: { options: Array<{ value: string; label: string }>; onChange: (value: string) => void; disabled?: boolean }) =>
      (jest.requireActual("react") as typeof import("react")).createElement("div", null, options.map((option) =>
        (jest.requireActual("react") as typeof import("react")).createElement("button", { key: option.value, "data-label": option.label, disabled, onClick: () => onChange(option.value) }, option.label))),
    ListRow: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      R.createElement("button", { "data-label": label, onClick: onPress, disabled }, label),
    TextLink: ({ label, onPress }: { label: string; onPress: () => void }) => R.createElement("button", { "data-label": label, onClick: onPress }, label),
    PasswordInput: (props: object) => R.createElement((require("react-native") as typeof import("react-native")).TextInput, props),
    Card: ({ children }: { children: ReactNode }) => R.createElement("section", null, children),
    Separator: () => null,
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {} }),
  };
});

import Enrol from "../src/nativeRoutes/enrol";

async function shown(plus: boolean, os: string, slot: "active" | "demo" | undefined = "active"): Promise<boolean> {
  mockPlus.value = plus;
  mockSlot.value = slot;
  (Platform as { OS: string }).OS = os;
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Enrol />); });
  return JSON.stringify(tree.toJSON()).includes("welcomeStandaloneTitle");
}

it("shows the standalone choice on Plus Android and Plus iOS only", async () => {
  expect(await shown(true, "android")).toBe(true);
  expect(await shown(false, "android")).toBe(false);
  expect(await shown(true, "ios")).toBe(true);
  expect(await shown(false, "ios")).toBe(false);
  expect(await shown(true, "web")).toBe(false);
});

it("does not offer standalone setup while the Demo slot is chosen (Path C accounts belong to Active)", async () => {
  expect(await shown(true, "android", "active")).toBe(true);
  expect(await shown(true, "android", "demo")).toBe(false);
});

it("shows the three mode choices and disables standalone until all server accounts are signed out", async () => {
  mockStandaloneAvailable.value = false;
  mockPlus.value = true;
  mockSlot.value = "active";
  (Platform as { OS: string }).OS = "android";
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Enrol />); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("welcomeScanTitle");
  expect(output).toContain("welcomeStandaloneTitle");
  expect(output).toContain("demoTryTitle");
  expect(output).toContain("standaloneLogoutRequired");
  expect(tree.root.findByProps({ "data-label": "welcomeStandaloneTitle" }).props.disabled).toBe(true);
});

it("shows the three choices before opening QR and manual server details", async () => {
  mockStandaloneAvailable.value = true;
  mockPlus.value = true;
  mockSlot.value = "active";
  (Platform as { OS: string }).OS = "android";
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Enrol />); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("welcomeScanTitle");
  expect(output).toContain("welcomeStandaloneTitle");
  expect(output).toContain("demoTryTitle");
  expect(output).not.toContain("standaloneWarning");
  // No duplicate headings: the old "Enroll This Device with Server" title is gone.
  expect(output).not.toContain("enrolServerTitle");
  expect(output.indexOf("welcomeScanTitle")).toBeLessThan(output.indexOf("welcomeManualTitle"));
  expect(output.indexOf("welcomeManualTitle")).toBeLessThan(output.indexOf("welcomeStandaloneTitle"));
  expect(output.indexOf("welcomeStandaloneTitle")).toBeLessThan(output.indexOf("demoTryTitle"));
  expect(tree.root.findAllByType("CameraView" as never)).toHaveLength(0);
  expect(tree.root.findAllByType(TextInput)).toHaveLength(0);

  await act(async () => tree.root.findByProps({ "data-label": "welcomeScanTitle" }).props.onClick());
  expect(tree.root.findAllByType("CameraView" as never)).toHaveLength(1);
  // The other ways in are hidden while scanning, and Cancel goes back to them.
  expect(tree.root.findAllByProps({ "data-label": "welcomeStandaloneTitle" })).toHaveLength(0);
  await act(async () => tree.root.findByProps({ "data-label": "cancel" }).props.onClick());
  await act(async () => tree.root.findByProps({ "data-label": "welcomeManualTitle" }).props.onClick());
  expect(tree.root.findAllByType(TextInput).length).toBeGreaterThan(0);
});
