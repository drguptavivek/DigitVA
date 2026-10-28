/** The standalone entry on /enrol is offered on Collect Plus (Android) only, and only while Active is chosen. */
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
  return JSON.stringify(tree.toJSON()).includes("standaloneEntry");
}

it("shows the standalone choice on Plus Android only", async () => {
  expect(await shown(true, "android")).toBe(true);
  expect(await shown(false, "android")).toBe(false);
  expect(await shown(true, "ios")).toBe(false);
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
  expect(output).toContain("enrolServerTitle");
  expect(output).toContain("enrolStandaloneTitle");
  expect(output).toContain("enrolDemoTitle");
  expect(output).toContain("standaloneLogoutRequired");
  expect(tree.root.findByProps({ "data-label": "standaloneEntry" }).props.disabled).toBe(true);
});

it("shows the three choices before opening QR and manual server details", async () => {
  mockStandaloneAvailable.value = true;
  mockPlus.value = true;
  mockSlot.value = "active";
  (Platform as { OS: string }).OS = "android";
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Enrol />); });
  const output = JSON.stringify(tree.toJSON());
  expect(output).toContain("enrolServerTitle");
  expect(output).toContain("enrolStandaloneTitle");
  expect(output).toContain("enrolDemoTitle");
  expect(output).not.toContain("standaloneWarning");
  expect(output.indexOf("enrolServerTitle")).toBeLessThan(output.indexOf("enrolStandaloneTitle"));
  expect(output.indexOf("enrolStandaloneTitle")).toBeLessThan(output.indexOf("enrolDemoTitle"));
  expect(tree.root.findAllByType("CameraView" as never)).toHaveLength(0);
  expect(tree.root.findAllByType(TextInput)).toHaveLength(0);

  await act(async () => tree.root.findByProps({ "data-label": "enrolTitle" }).props.onClick());
  expect(tree.root.findAllByType("CameraView" as never)).toHaveLength(1);
  expect(tree.root.findAllByType(TextInput).length).toBeGreaterThan(0);
});
