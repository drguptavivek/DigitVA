import React from "react";
import { act, create } from "react-test-renderer";

const mockUseAppState = jest.fn();
const mockBiometricEnabled = jest.fn();

jest.mock("react-native", () => ({ Platform: { OS: "web" }, Text: "text" }));
jest.mock("expo-router", () => ({ useRouter: jest.fn() }));
jest.mock("expo-secure-store", () => ({ canUseBiometricAuthentication: jest.fn() }));
jest.mock("../src/AppState", () => ({ useAppState: mockUseAppState }));
jest.mock("../src/vault", () => ({ biometricEnabled: mockBiometricEnabled }));
jest.mock("../src/browserScreens", () => ({ SettingsScreen: () => require("react").createElement("web-settings") }));
jest.mock("../src/i18n", () => ({ t: (key: string) => key, UI_LOCALES: [] }));
jest.mock("../src/ui", () => ({ Button: "button", Screen: "screen", useUiStyles: jest.fn() }));

import Settings from "../app/settings";

it("renders web settings without touching native account or vault state", () => {
  let tree: ReturnType<typeof create>;
  act(() => {
    tree = create(<Settings />);
  });
  expect(tree!.toJSON()).toEqual({ type: "web-settings", props: {}, children: null });
  expect(mockUseAppState).not.toHaveBeenCalled();
  expect(mockBiometricEnabled).not.toHaveBeenCalled();
});
