/** Enrol screen, "I have a sign-in code" (docs/policy/mobile-sign-in.md section 3): redeem in the app, show the
 * password once, sign in with it without retyping; a code typed as a password is routed to the code form. */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text, TextInput } from "react-native";

const SERVER = "https://digitva.causeofdeathindia.com";
const GENERATED = "maple-otter-candle-4821";
const mockRouter = { replace: jest.fn(), push: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
const mockReload = jest.fn(async () => undefined);
const mockLockNow = jest.fn(async () => true);
const mockRedeemCode = jest.fn<Promise<string>, unknown[]>();
const mockPasswordEnrol = jest.fn<Promise<{ account: { user_id: string; name: string }; projects: Array<{ project_id: string; name: string }> }>, unknown[]>();

jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Pixel", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({ useCameraPermissions: () => [{ granted: true }, jest.fn()], CameraView: "CameraView" }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: mockReload, lockNow: mockLockNow }) }));
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
import { ApiError } from "../src/api";
import { formatSignInCode, looksLikeSignInCode } from "../src/nativeAuthLinks";

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<Enrol />);
  });
  return tree;
}
const press = (tree: ReactTestRenderer, label: string) =>
  act(async () => tree.root.findByProps({ "data-label": label }).props.onClick());
const field = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAllByType(TextInput).find((input) => input.props.accessibilityLabel === label)!;
const type = (tree: ReactTestRenderer, label: string, value: string) => act(() => field(tree, label).props.onChangeText(value));
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());
const title = (tree: ReactTestRenderer) => tree.root.findByType("main" as never).props["data-title"];
/** The password as "Code accepted" shows it, or undefined when it is not on screen. */
const shownPassword = (tree: ReactTestRenderer) =>
  tree.root.findAllByType(Text).find((node) => node.props.selectable && node.props.children === GENERATED)?.props.children;

async function fillCodeForm(tree: ReactTestRenderer, code = "k7pqm3xr") {
  await press(tree, "redeemCode");
  type(tree, "enrolServerAddress", SERVER);
  await press(tree, "segment-mobile");
  type(tree, "mobile", "98765 43210");
  type(tree, "signInCodeLabel", code);
  await press(tree, "terms-switch");
}

let logs: jest.SpyInstance[];
beforeEach(() => {
  jest.clearAllMocks();
  logs = (["log", "info", "warn", "error", "debug"] as const).map((level) => jest.spyOn(console, level).mockImplementation(() => undefined));
});
afterEach(() => logs.forEach((spy) => spy.mockRestore()));
const logged = (secret: string) => logs.some((spy) => JSON.stringify(spy.mock.calls).includes(secret));

it("redeems a code, shows the password once, and I have saved it signs in with that password", async () => {
  mockRedeemCode.mockResolvedValueOnce(GENERATED);
  mockPasswordEnrol.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: [] });
  const tree = await render();
  await fillCodeForm(tree);
  // Formatted as typed: capitals, XXXX-XXXX, monospaced.
  expect(field(tree, "signInCodeLabel").props.value).toBe("K7PQ-M3XR");
  expect(field(tree, "signInCodeLabel").props.autoCapitalize).toBe("characters");
  expect(field(tree, "signInCodeLabel").props.autoCorrect).toBe(false);
  await press(tree, "signInCodeSubmit");
  expect(mockRedeemCode).toHaveBeenCalledWith(SERVER, "+919876543210", "K7PQ-M3XR");
  expect(mockPasswordEnrol).not.toHaveBeenCalled();
  expect(title(tree)).toBe("enrolCodeAccepted");
  expect(shownPassword(tree)).toBe(GENERATED);

  await press(tree, "signInCodeSaved");
  expect(mockLockNow).toHaveBeenCalledTimes(1);
  expect(mockPasswordEnrol).toHaveBeenCalledWith(SERVER, "+919876543210", GENERATED, "Pixel", "1.0.0", undefined);
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
  expect(shownPassword(tree)).toBeUndefined();
  expect(logged(GENERATED) || logged("K7PQ")).toBe(false);
});

it("needs the terms tick and a code-shaped code before it sends anything", async () => {
  const tree = await render();
  await press(tree, "redeemCode");
  type(tree, "enrolServerAddress", SERVER);
  type(tree, "email", "asha@example.org");
  type(tree, "signInCodeLabel", "K7PQ");
  await press(tree, "terms-switch");
  expect(tree.root.findByProps({ "data-label": "signInCodeSubmit" }).props.disabled).toBe(true);
  type(tree, "signInCodeLabel", "K7PQM3XR");
  expect(tree.root.findByProps({ "data-label": "signInCodeSubmit" }).props.disabled).toBe(false);
  await press(tree, "terms-switch");
  expect(tree.root.findByProps({ "data-label": "signInCodeSubmit" }).props.disabled).toBe(true);
});

it("a code typed into the Password box opens the code form with it once the password is refused", async () => {
  mockPasswordEnrol.mockRejectedValueOnce(new ApiError(401, "invalid_credentials"));
  mockRedeemCode.mockResolvedValueOnce(GENERATED);
  const tree = await render();
  await press(tree, "welcomeManualTitle");
  type(tree, "enrolServerAddress", SERVER);
  type(tree, "email", "asha@example.org");
  type(tree, "password", "k7pq-m3xr");
  await press(tree, "enrolManualSubmit");
  // Password sign-in goes first (an old password could have this shape), then the code form, prefilled.
  expect(mockPasswordEnrol).toHaveBeenCalledWith(SERVER, "asha@example.org", "k7pq-m3xr", "Pixel", "1.0.0", undefined);
  expect(title(tree)).toBe("redeemCode");
  expect(text(tree)).toContain("signInCodeFromPassword");
  expect(field(tree, "signInCodeLabel").props.value).toBe("K7PQ-M3XR");
  expect(field(tree, "email").props.value).toBe("asha@example.org");
  expect(mockRedeemCode).not.toHaveBeenCalled();
  await press(tree, "terms-switch");
  await press(tree, "signInCodeSubmit");
  expect(mockRedeemCode).toHaveBeenCalledWith(SERVER, "asha@example.org", "K7PQ-M3XR");
  expect(title(tree)).toBe("enrolCodeAccepted");
});

it("a refused password that is no code shape stays a sign-in error, and a legacy 6-digit code is routed", async () => {
  mockPasswordEnrol.mockRejectedValue(new ApiError(401, "invalid_credentials"));
  const tree = await render();
  await press(tree, "welcomeManualTitle");
  type(tree, "enrolServerAddress", SERVER);
  type(tree, "email", "asha@example.org");
  type(tree, "password", "maple-otter-candle-4821");
  await press(tree, "enrolManualSubmit");
  expect(title(tree)).toBe("welcomeManualTitle");
  expect(text(tree)).toContain("generic error");
  type(tree, "password", "123456");
  await press(tree, "enrolManualSubmit");
  expect(title(tree)).toBe("redeemCode");
});

it("after a redemption at the device limit shows the chooser and retries with the same password", async () => {
  const { Alert } = jest.requireActual("react-native") as typeof import("react-native");
  const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  const devices = [{ device_id: "d-old", label: "Old phone", last_seen_at: null, unsent_count: null }];
  mockRedeemCode.mockResolvedValueOnce(GENERATED);
  mockPasswordEnrol
    .mockRejectedValueOnce(new ApiError(409, "device_limit", undefined, undefined, { code: "device_limit", devices }))
    .mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: [] });
  const tree = await render();
  await fillCodeForm(tree);
  await press(tree, "signInCodeSubmit");
  await press(tree, "signInCodeSaved");
  expect(title(tree)).toBe("deviceLimitTitle");
  await press(tree, "Old phone");
  const actions = alert.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
  await act(async () => actions.find((a) => a.text === "deviceLimitConfirm")!.onPress!());
  expect(mockPasswordEnrol).toHaveBeenLastCalledWith(SERVER, "+919876543210", GENERATED, "Pixel", "1.0.0", "d-old");
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
  expect(mockRedeemCode).toHaveBeenCalledTimes(1);
  alert.mockRestore();
});

it("keeps the password on a failed sign-in for a retry, and Cancel drops it", async () => {
  mockRedeemCode.mockResolvedValueOnce(GENERATED);
  mockPasswordEnrol.mockRejectedValueOnce(new TypeError("Network request failed"));
  const tree = await render();
  await fillCodeForm(tree);
  await press(tree, "signInCodeSubmit");
  await press(tree, "signInCodeSaved");
  expect(text(tree)).toContain("generic error");
  expect(shownPassword(tree)).toBe(GENERATED);
  await press(tree, "cancel");
  expect(shownPassword(tree)).toBeUndefined();
  expect(text(tree)).not.toContain(GENERATED);
  expect(title(tree)).toBe("enrolTitle");
});

it("explains a wrong code and an older server, and keeps the code to fix a typo", async () => {
  mockRedeemCode.mockRejectedValueOnce(new ApiError(401, "invalid_code")).mockRejectedValueOnce(new ApiError(404, "not_found"));
  const tree = await render();
  await fillCodeForm(tree);
  await press(tree, "signInCodeSubmit");
  expect(text(tree)).toContain("errSignInCodeInvalid");
  expect(field(tree, "signInCodeLabel").props.value).toBe("K7PQ-M3XR");
  await press(tree, "signInCodeSubmit");
  expect(text(tree)).toContain("errSignInCodeUnsupported");
  expect(mockPasswordEnrol).not.toHaveBeenCalled();
});

it("reads a code's shape as the server does and formats it as typed", () => {
  for (const value of ["K7PQ-M3XR", "k7pq m3xr", "K7PQM3XR", " k7pq-m3xr ", "123456"]) expect(looksLikeSignInCode(value)).toBe(true);
  // Look-alikes 0 O 1 I L are not code characters; generated passwords and other lengths are not codes.
  for (const value of ["K7PQ-M3X0", "K7PQ-M3XL", "K7PQ-M3X", "K7PQ-M3XRA", "12345", "1234567", "maple-otter-candle-4821", ""]) {
    expect(looksLikeSignInCode(value)).toBe(false);
  }
  expect(formatSignInCode("k7pq")).toBe("K7PQ");
  expect(formatSignInCode("k7pqm")).toBe("K7PQ-M");
  expect(formatSignInCode("K7PQ-M3XR99")).toBe("K7PQ-M3XR");
  expect(formatSignInCode("123456")).toBe("1234-56");
});
