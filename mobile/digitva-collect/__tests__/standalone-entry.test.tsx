/** The standalone entry on /enrol is offered on Collect Plus (Android) only. */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";
import { Platform } from "react-native";

const mockPlus = { value: true };
jest.mock("expo-router", () => ({ useRouter: () => ({ replace: jest.fn(), push: jest.fn() }) }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Pixel", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ useCameraPermissions: () => [{ granted: true }, jest.fn()], CameraView: "CameraView" }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: jest.fn() }) }));
jest.mock("../src/auth", () => ({ redeemSignInQr: jest.fn(), enrolDevice: jest.fn() }));
jest.mock("../src/api", () => ({ ApiError: class extends Error {} }));
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus.value }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label }: { label: string }) => R.createElement("button", null, label),
    Screen: ({ children }: { children: ReactNode }) => R.createElement("main", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {} }),
  };
});

import Enrol from "../src/nativeRoutes/enrol";

async function shown(plus: boolean, os: string): Promise<boolean> {
  mockPlus.value = plus;
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
