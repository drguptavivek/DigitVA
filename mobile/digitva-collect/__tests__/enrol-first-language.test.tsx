/** Enrol screen on a fresh install: the UI language is asked first (owner 2026-11-16), once. */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockRouter = { replace: jest.fn(), push: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
const mockReload = jest.fn(async () => undefined);
const mockLockNow = jest.fn(async () => true);
const mockRedeemCode = jest.fn();
const mockPasswordEnrol = jest.fn();
const mockChoose = jest.fn(async () => undefined);
const mockState: Record<string, unknown> = {};
jest.mock("../src/uiPacks", () => ({
  useUiLanguages: () => [
    { code: "en", label: "English", language: "en" },
    { code: "hi", label: "हिन्दी", language: "hi" },
  ],
}));
jest.mock("../src/ui/controls", () => {
  const R = jest.requireActual("react") as typeof React;
  return {
    MenuChoiceRow: ({ label, onPress, selected }: { label: string; onPress(): void; selected: boolean }) =>
      R.createElement("button", { "data-label": `lang-${label}`, "data-selected": selected, onClick: onPress }, label),
  };
});
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Pixel", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ useCameraPermissions: () => [{ granted: true }, jest.fn()], CameraView: "CameraView" }));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
jest.mock("../src/auth", () => ({
  redeemSignInCode: (...args: unknown[]) => mockRedeemCode(...args),
  passwordEnrolAndSignIn: (...args: unknown[]) => mockPasswordEnrol(...args),
  redeemSignInQr: jest.fn(),
  enrolDevice: jest.fn(),
  setDeviceHomeProject: jest.fn(),
}));
jest.mock("../src/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code?: string;
    payload?: Record<string, unknown>;
    constructor(status: number, code?: string, _redirect?: string, _csrf?: unknown, payload?: Record<string, unknown>) {
      super(`HTTP ${status}`);
      this.status = status;
      this.code = code;
      this.payload = payload;
    }
  },
}));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : "") }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  const RN = jest.requireActual("react-native") as typeof import("react-native");
  const pressable = ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
    R.createElement("button", { "data-label": label, disabled, onClick: onPress }, label);
  return {
    Button: pressable,
    TextLink: pressable,
    ListRow: ({ label, onPress, disabled, trailing }: { label: string; onPress?: () => void; disabled?: boolean; trailing?: ReactNode }) =>
      R.createElement("button", { "data-label": label, disabled, onClick: onPress }, label, trailing),
    Screen: ({ title, children }: { title: string; children: ReactNode }) => R.createElement("main", { "data-title": title }, children),
    errorText: () => "generic error",
    Notice: ({ children }: { children: ReactNode }) => R.createElement(RN.Text, null, children),
    SegmentedControl: ({ options, onChange }: { options: Array<{ value: string; label: string }>; onChange: (value: string) => void }) =>
      R.createElement("div", null, options.map((option) =>
        R.createElement("button", { key: option.value, "data-label": `segment-${option.value}`, onClick: () => onChange(option.value) }, option.label))),
    PasswordInput: (props: object) => R.createElement(RN.TextInput, { ...props, secureTextEntry: true }),
    ThemedSwitch: (props: { onValueChange: (value: boolean) => void; value: boolean }) =>
      R.createElement("switch", { "data-label": "terms-switch", onClick: () => props.onValueChange(!props.value) }),
    Card: ({ children }: { children: ReactNode }) => R.createElement("section", null, children),
    Separator: () => null,
    monoFont: "monospace",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, headline: {} }),
  };
});

import Enrol from "../src/nativeRoutes/enrol";

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<Enrol />); });
  return tree;
}
const title = (tree: ReactTestRenderer) => tree.root.findByType("main" as never).props["data-title"];

beforeEach(() => {
  mockChoose.mockClear();
  Object.assign(mockState, { reload: mockReload, lockNow: mockLockNow, chooseUiLocale: mockChoose, uiLocale: "en" });
});

it("asks the language first on a fresh install and saves the choice", async () => {
  mockState.uiLocaleChosen = false;
  const tree = await render();
  expect(title(tree)).toBe("chooseLanguageTitle");
  expect(tree.root.findByProps({ "data-label": "lang-English" }).props["data-selected"]).toBe(true);
  await act(async () => tree.root.findByProps({ "data-label": "lang-हिन्दी" }).props.onClick());
  expect(mockChoose).toHaveBeenCalledWith("hi");
});

it("goes straight to sign-in once a language is saved", async () => {
  mockState.uiLocaleChosen = true;
  const tree = await render();
  expect(title(tree)).toBe("enrolTitle");
  expect(tree.root.findAllByProps({ "data-label": "lang-English" })).toHaveLength(0);
});
