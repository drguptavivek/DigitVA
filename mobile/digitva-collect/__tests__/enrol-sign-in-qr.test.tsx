/** Enrol screen: a scanned sign-in QR is confirmed, redeemed, and leads to PIN setup; every refusal is one message. */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { TextInput } from "react-native";

const TOKEN = "SignInTokenSignInTokenSignInToken123";
const SERVER = "https://digitva.causeofdeathindia.com";
const mockRouter = { replace: jest.fn(), push: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
const mockReload = jest.fn(async () => undefined);
const mockRedeem = jest.fn<Promise<{ account: { user_id: string; name: string }; projects: Array<{ project_id: string; name: string }> }>, unknown[]>();
const mockEnrol = jest.fn(async (..._args: unknown[]) => undefined);
const mockPasswordEnrol = jest.fn<Promise<{ account: { user_id: string; name: string }; projects: Array<{ project_id: string; name: string }> }>, unknown[]>();
const mockErrorText = jest.fn(() => "generic error");
const mockSetHome = jest.fn(async (..._args: unknown[]) => undefined);

jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { deviceName: "Pixel", expoConfig: { version: "1.0.0" } } }));
jest.mock("expo-camera", () => ({
  useCameraPermissions: () => [{ granted: true }, jest.fn()],
  CameraView: "CameraView",
}));
const mockLockNow = jest.fn(async () => true);
jest.mock("../src/AppState", () => ({ useAppState: () => ({ reload: mockReload, lockNow: mockLockNow }) }));
jest.mock("../src/auth", () => ({
  redeemSignInQr: (...args: unknown[]) => mockRedeem(...args),
  enrolDevice: (...args: unknown[]) => mockEnrol(...args),
  passwordEnrolAndSignIn: (...args: unknown[]) => mockPasswordEnrol(...args),
  setDeviceHomeProject: (...args: unknown[]) => mockSetHome(...args),
}));
jest.mock("../src/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code?: string;
    constructor(status: number, code?: string) {
      super(`HTTP ${status}`);
      this.status = status;
      this.code = code;
    }
  },
}));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : "") }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    Screen: ({ children }: { children: ReactNode }) => ReactActual.createElement("main", null, children),
    errorText: () => mockErrorText(),
    // The petrol notice as a plain text (an alert for error and warning, as the real one), so the message assertions keep reading its words.
    Notice: ({ children, testID, tone }: { children: React.ReactNode; testID?: string; tone?: string }) =>
      (jest.requireActual("react") as typeof import("react")).createElement((require("react-native") as typeof import("react-native")).Text, { accessibilityRole: tone === "error" || tone === "warning" ? "alert" : undefined, testID }, children),
    SegmentedControl: ({ options, onChange, disabled }: { options: Array<{ value: string; label: string }>; onChange: (value: string) => void; disabled?: boolean }) =>
      (jest.requireActual("react") as typeof import("react")).createElement("div", null, options.map((option) =>
        (jest.requireActual("react") as typeof import("react")).createElement("button", { key: option.value, "data-label": option.label, disabled, onClick: () => onChange(option.value) }, option.label))),
    // Welcome option rows and text links press like buttons; the password field keeps its masked TextInput.
    ListRow: ({ label, onPress, disabled, value }: { label: string; onPress?: () => void; disabled?: boolean; value?: string }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label, value),
    TextLink: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    PasswordInput: (props: object) => ReactActual.createElement((require("react-native") as typeof import("react-native")).TextInput, { ...props, secureTextEntry: true }),
    Card: ({ children }: { children: ReactNode }) => ReactActual.createElement("section", null, children),
    Separator: () => null,
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {} }),
  };
});

import Enrol from "../src/nativeRoutes/enrol";
import { ApiError } from "../src/api";

const signInQr = JSON.stringify({ v: 1, server: SERVER, sign_in: TOKEN });
const enrolQr = JSON.stringify({ v: 1, server: SERVER, enroll: "AbCdEf123456_-x", project: "UNSW01" });

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<Enrol />);
  });
  return tree;
}
const scan = (tree: ReactTestRenderer, data: string) =>
  act(() => tree.root.findByType("CameraView" as never).props.onBarcodeScanned({ data }));
const press = (tree: ReactTestRenderer, label: string) =>
  act(async () => tree.root.findByProps({ "data-label": label }).props.onClick());
const enterServer = (tree: ReactTestRenderer) => press(tree, "welcomeScanTitle");
/** Opens the server-and-password form from Welcome (a no-op when it is already open). */
const enterManual = async (tree: ReactTestRenderer) => {
  if (tree.root.findAllByProps({ "data-label": "welcomeManualTitle" }).length) await press(tree, "welcomeManualTitle");
};
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

let logs: jest.SpyInstance[];
beforeEach(() => {
  jest.clearAllMocks();
  logs = (["log", "info", "warn", "error", "debug"] as const).map((level) => jest.spyOn(console, level).mockImplementation(() => undefined));
});
afterEach(() => logs.forEach((spy) => spy.mockRestore()));

const loggedAnything = () => logs.some((spy) => JSON.stringify(spy.mock.calls).includes(TOKEN));

it("shows the server and waits for confirmation before redeeming a sign-in QR", async () => {
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  expect(text(tree)).toContain("digitva.causeofdeathindia.com");
  expect(text(tree)).toContain("enrolConfirmSignInHint");
  expect(text(tree)).not.toContain("interviewProject");
  expect(mockRedeem).not.toHaveBeenCalled();
});

it("redeems on confirm, then goes to PIN setup through unlock with the refresh flag", async () => {
  mockRedeem.mockResolvedValue({ account: { user_id: "u1", name: "Asha" }, projects: [] });
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(mockRedeem).toHaveBeenCalledWith(SERVER, TOKEN, "Pixel", "1.0.0");
  expect(mockEnrol).not.toHaveBeenCalled();
  expect(mockReload).toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
  expect(loggedAnything()).toBe(false);
});

it("saves and locks every store before redeeming or enrolling, and sends nothing when that fails", async () => {
  mockLockNow.mockResolvedValueOnce(false).mockResolvedValueOnce(false);
  for (const qr of [signInQr, enrolQr]) {
    const tree = await render();
    await enterServer(tree);
    scan(tree, qr);
    await press(tree, "enrolConfirm");
    expect(text(tree)).toContain("errGeneric");
  }
  expect(mockLockNow).toHaveBeenCalledTimes(2);
  expect(mockRedeem).not.toHaveBeenCalled();
  expect(mockEnrol).not.toHaveBeenCalled();
});

it("shows one message for every refusal and never the token", async () => {
  for (const status of [404, 400]) {
    mockRedeem.mockRejectedValueOnce(new ApiError(status, "sign_in_qr_invalid"));
    const tree = await render();
    await enterServer(tree);
    scan(tree, signInQr);
    await press(tree, "enrolConfirm");
    expect(text(tree)).toContain("errSignInQrInvalid");
    expect(text(tree)).not.toContain(TOKEN);
    expect(mockErrorText).not.toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalled();
  }
  expect(loggedAnything()).toBe(false);
});

it("tells a rate-limited scan to wait, not that the QR is invalid", async () => {
  mockRedeem.mockRejectedValueOnce(new ApiError(429, "rate_limited"));
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(text(tree)).toContain("errSignInQrRateLimited");
  expect(text(tree)).not.toContain("errSignInQrInvalid");
});

it("names expiry, prior use and another server in the invalid-QR message", () => {
  const en = require("../src/strings/en.json").errSignInQrInvalid as string;
  for (const word of ["expired", "already been scanned", "different DigitVA server"]) expect(en).toContain(word);
});

it("redeems for a coder-only account the same way and goes to unlock, where the gate picks the coding screens", async () => {
  mockRedeem.mockResolvedValue({ account: { user_id: "coder1", name: "Coder" }, projects: [] });
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "coder1", refresh: "1" } });
});

it("treats a network failure as an ordinary error, not as an invalid QR", async () => {
  mockRedeem.mockRejectedValueOnce(new Error("network"));
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(text(tree)).toContain("generic error");
  expect(text(tree)).not.toContain("errSignInQrInvalid");
});

it("rejects a sign-in QR for a server outside the allowed domain before anything is sent", async () => {
  const tree = await render();
  await enterServer(tree);
  scan(tree, JSON.stringify({ v: 1, server: "https://evil.io", sign_in: TOKEN }));
  expect(text(tree)).toContain("errServerNotAllowed");
  expect(text(tree)).not.toContain(TOKEN);
  expect(mockRedeem).not.toHaveBeenCalled();
});

it("still enrols from an enrolment QR", async () => {
  const tree = await render();
  await enterServer(tree);
  scan(tree, enrolQr);
  // Confirm server names the server and the project as rows, with one primary action.
  expect(text(tree)).toContain("interviewProject");
  expect(text(tree)).toContain("UNSW01");
  expect(text(tree)).not.toContain("enrolManualSubmit");
  expect(text(tree)).not.toContain("demoTryTitle");
  await press(tree, "enrolConfirm");
  expect(mockEnrol).toHaveBeenCalledWith(SERVER, "AbCdEf123456_-x", "Pixel", "1.0.0");
  expect(mockRedeem).not.toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/");
});

async function fillManual(tree: ReactTestRenderer, password = "private-password") {
  await enterManual(tree);
  for (const [label, value] of [["enrolServerAddress", SERVER], ["email", "asha@example.org"], ["password", password]]) {
    act(() => tree.root.findAllByType(TextInput).find((input) => input.props.accessibilityLabel === label)!.props.onChangeText(value));
  }
}

it("enrols manually, clears the password and follows the QR unlock journey", async () => {
  mockPasswordEnrol.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: [] });
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  expect(mockLockNow).toHaveBeenCalledTimes(1);
  expect(mockPasswordEnrol).toHaveBeenCalledWith(SERVER, "asha@example.org", "private-password", "Pixel", "1.0.0");
  expect(mockReload).toHaveBeenCalledTimes(1);
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
  expect(tree.root.findAllByType(TextInput).find((input) => input.props.secureTextEntry)!.props.value).toBe("");
  expect(mockRedeem).not.toHaveBeenCalled();
  expect(mockEnrol).not.toHaveBeenCalled();
  expect(logs.some((spy) => JSON.stringify(spy.mock.calls).includes("private-password"))).toBe(false);
});

it("clears a refused manual password, explains an unsupported server and makes no QR fallback", async () => {
  mockPasswordEnrol.mockRejectedValueOnce(new ApiError(404, "not_found"));
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  expect(text(tree)).toContain("errPasswordEnrolUnsupported");
  expect(tree.root.findAllByType(TextInput).find((input) => input.props.secureTextEntry)!.props.value).toBe("");
  expect(mockReload).not.toHaveBeenCalled();
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(mockRedeem).not.toHaveBeenCalled();
  expect(mockEnrol).not.toHaveBeenCalled();
});

it("clears manual credentials when locking fails and when the form unmounts", async () => {
  mockLockNow.mockResolvedValueOnce(false);
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  expect(mockPasswordEnrol).not.toHaveBeenCalled();
  expect(tree.root.findAllByType(TextInput).find((input) => input.props.secureTextEntry)!.props.value).toBe("");
  await fillManual(tree);
  act(() => tree.unmount());
  const remounted = await render();
  await enterManual(remounted);
  expect(remounted.root.findAllByType(TextInput).find((input) => input.props.secureTextEntry)!.props.value).toBe("");
});

it("uses the existing canonical mobile identifier in the manual form", async () => {
  mockPasswordEnrol.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: [] });
  const tree = await render();
  await enterManual(tree);
  await press(tree, "mobile");
  for (const [label, value] of [["enrolServerAddress", SERVER], ["mobile", "9876543210"], ["password", "pw"]]) {
    act(() => tree.root.findAllByType(TextInput).find((input) => input.props.accessibilityLabel === label)!.props.onChangeText(value));
  }
  await press(tree, "enrolManualSubmit");
  expect(mockPasswordEnrol).toHaveBeenCalledWith(SERVER, "+919876543210", "pw", "Pixel", "1.0.0");
});

/** Labels and texts in render order, so an error's place next to its button can be asserted. */
function order(tree: ReactTestRenderer): string[] {
  const out: string[] = [];
  const walk = (node: unknown) => {
    if (typeof node === "string") out.push(node);
    else if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === "object") {
      const { props, children } = node as { props?: { "data-label"?: string }; children?: unknown };
      if (props?.["data-label"]) out.push(props["data-label"]);
      else walk(children);
    }
  };
  walk(tree.toJSON());
  return out;
}

it("shows a pasted code's error right under its Enrol button and clears it when the box is edited", async () => {
  const tree = await render();
  await enterServer(tree);
  const paste = () => tree.root.findAllByType(TextInput).find((input) => input.props.multiline)!;
  act(() => paste().props.onChangeText("{“v”:2}"));
  await press(tree, "enrolSubmit");
  const items = order(tree);
  expect(items).toContain("errBadQr");
  expect(items.indexOf("errBadQr")).toBe(items.indexOf("enrolSubmit") + 1);
  // The scanner is its own view: the server-and-password form is not stacked under it.
  expect(items).not.toContain("enrolManualSubmit");
  act(() => paste().props.onChangeText("{"));
  expect(order(tree)).not.toContain("errBadQr");
});

it("shows a login error right under the login button", async () => {
  mockPasswordEnrol.mockRejectedValueOnce(new Error("network"));
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  const items = order(tree);
  expect(items).toContain("generic error");
  expect(items.indexOf("generic error")).toBe(items.indexOf("enrolManualSubmit") + 1);
});

const TWO_PROJECTS = [{ project_id: "P1", name: "Project One" }, { project_id: "P2", name: "Project Two" }];

it("asks a person with several projects to pick one, sets it, then goes to unlock", async () => {
  mockPasswordEnrol.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: TWO_PROJECTS });
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  expect(text(tree)).toContain("enrolChooseProjectHint");
  expect(text(tree)).toContain("Project One");
  expect(mockRouter.replace).not.toHaveBeenCalled();
  await press(tree, "Project Two");
  expect(mockSetHome).toHaveBeenCalledWith("u1", "P2");
  expect(mockReload).toHaveBeenCalledTimes(2); // after enrolment, then after the pick
  expect(mockSetHome.mock.invocationCallOrder[0]).toBeLessThan(mockReload.mock.invocationCallOrder[1]);
  expect(mockReload.mock.invocationCallOrder[1]).toBeLessThan(mockRouter.replace.mock.invocationCallOrder[0]);
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});

it("asks after a sign-in QR too, and keeps the picker with an error when setting the project fails", async () => {
  mockRedeem.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: TWO_PROJECTS });
  mockSetHome.mockRejectedValueOnce(new Error("offline"));
  const tree = await render();
  await enterServer(tree);
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  await press(tree, "Project One");
  expect(mockSetHome).toHaveBeenCalledWith("u1", "P1");
  expect(mockRouter.replace).not.toHaveBeenCalled();
  expect(text(tree)).toContain("generic error");
  expect(text(tree)).toContain("Project Two");
});

it("does not ask when exactly one project is eligible", async () => {
  mockPasswordEnrol.mockResolvedValueOnce({ account: { user_id: "u1", name: "Asha" }, projects: [TWO_PROJECTS[0]] });
  const tree = await render();
  await fillManual(tree);
  await press(tree, "enrolManualSubmit");
  expect(text(tree)).not.toContain("enrolChooseProjectHint");
  expect(mockSetHome).not.toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});
