/**
 * Sign in again on a revoked or removed phone (digitva-dbcw): `not_enrolled` asks to enrol again; yes runs the
 * password enrolment on the account's own server, a `409 device_limit` there opens the picker and retries with
 * `replaceDeviceId`. Local work surviving the enrolment is covered in auth.test.ts (passwordEnrolAndSignIn).
 */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Alert, TextInput } from "react-native";

const mockRouter = { replace: jest.fn(), push: jest.fn(), dismissTo: jest.fn() };
const mockSignIn = jest.fn<Promise<{ user_id: string }>, unknown[]>();
const mockRecover = jest.fn<Promise<void>, unknown[]>();
const mockEnrol = jest.fn<Promise<{ account: { user_id: string } }>, unknown[]>();
const mockLockNow = jest.fn(async () => true);

let mockParams: Record<string, string> = {};
jest.mock("expo-router", () => ({ useRouter: () => mockRouter, useLocalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ reload: async () => undefined, accounts: [{ user_id: "u1", name: "Asha", server: "https://example.org", needs_sign_in: true }], device: undefined,
    lockNow: () => mockLockNow() }),
}));
jest.mock("../src/auth", () => ({
  signIn: (...args: unknown[]) => mockSignIn(...args),
  passwordEnrolAndSignIn: (...args: unknown[]) => mockEnrol(...args),
  loadActiveSlot: async () => "active",
  loadDevice: async () => undefined,
  forgetDevice: async () => undefined,
  recoverSignOut: (...args: unknown[]) => mockRecover(...args),
  verifyPasswordForDelete: async () => undefined,
  WrongAccountError: class WrongAccountError extends Error {},
}));
jest.mock("expo-constants", () => ({ deviceName: "Pixel" }));
jest.mock("../src/i18n", () => ({ t: (key: string, vars?: object) => key + (vars ? JSON.stringify(vars) : "") }));
jest.mock("../src/ui/interviewRows", () => ({ formatWhen: (value?: string | null) => (value ? "WHEN" : "") }));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as typeof React;
  const { Text, TextInput: Input } = jest.requireActual("react-native") as typeof import("react-native");
  const press = ({ label, onPress, disabled, testID }: { label: string; onPress?: () => void; disabled?: boolean; testID?: string }) =>
    R.createElement("button", { "data-label": label, disabled, onClick: onPress, testID }, label);
  return {
    Button: press,
    TextLink: press,
    ListRow: ({ secondary, tone, ...props }: { label: string; secondary?: string; tone?: string; onPress?: () => void; testID?: string }) =>
      R.createElement("section", { "data-tone": tone }, press(props), secondary),
    Screen: ({ title, children }: { title: string; children: ReactNode }) => R.createElement("main", { title }, children),
    Card: ({ children }: { children: ReactNode }) => R.createElement("section", null, children),
    Separator: () => null,
    Notice: ({ children }: { children: ReactNode }) => R.createElement(Text, { accessibilityRole: "alert" }, children),
    FieldLabel: () => null,
    SegmentedControl: () => null,
    TextField: (props: object) => R.createElement(Input, props),
    PasswordInput: (props: object) => R.createElement(Input, { ...props, secureTextEntry: true }),
    errorText: (error: { code?: string }) => (error.code === "device_limit" ? "deviceLimit" : "generic"),
    useUiStyles: () => ({ text: {}, muted: {}, phoneInputRow: {}, phonePrefix: {}, phoneInput: {} }),
  };
});

import SignIn from "../src/nativeRoutes/sign-in";
import { ApiError } from "../src/api";

const notEnrolled = () => new Error("not_enrolled");
const limited = (devices: unknown) => new ApiError(409, "device_limit", undefined, undefined, { code: "device_limit", devices });
const PHONES = [{ device_id: "d-old", label: "Old phone", last_seen_at: null, unsent_count: 0 }];

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<SignIn />); });
  return tree;
}
const button = (tree: ReactTestRenderer, label: string) =>
  tree.root.find((node) => node.type === "button" && node.props["data-label"] === label);
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());
const title = (tree: ReactTestRenderer) => tree.root.findByType("main").props.title;

async function submit(tree: ReactTestRenderer) {
  const [identifier, password] = tree.root.findAllByType(TextInput);
  await act(async () => { identifier.props.onChangeText("a@example.org"); });
  await act(async () => { password.props.onChangeText("pw"); });
  await act(async () => { button(tree, "signIn").props.onClick(); });
}

beforeEach(() => {
  mockParams = { userId: "u1" };
  mockSignIn.mockReset().mockRejectedValue(notEnrolled());
  mockEnrol.mockReset();
  mockLockNow.mockClear();
  mockRouter.dismissTo.mockReset();
});
afterEach(() => jest.restoreAllMocks());

it("Sign in again on a phone no longer enrolled asks to enrol again, not the generic error", async () => {
  const tree = await render();
  await submit(tree);
  expect(title(tree)).toBe("notEnrolledTitle");
  expect(text(tree)).toContain("notEnrolledBody");
  expect(text(tree)).not.toContain("generic");
  expect(mockEnrol).not.toHaveBeenCalled();

  await act(async () => { button(tree, "cancel").props.onClick(); });
  expect(title(tree)).toBe("signInTitle");
  expect(mockEnrol).not.toHaveBeenCalled();
});

it("yes locks the stores and enrols on the account's own server with the same account, then unlocks it", async () => {
  mockEnrol.mockResolvedValueOnce({ account: { user_id: "u1" } });
  const tree = await render();
  await submit(tree);
  await act(async () => { button(tree, "notEnrolledConfirm").props.onClick(); });

  expect(mockLockNow).toHaveBeenCalled();
  expect(mockEnrol).toHaveBeenCalledTimes(1);
  expect(mockEnrol.mock.calls[0]).toEqual(["https://example.org", "a@example.org", "pw", "Pixel", expect.any(String), undefined]);
  expect(mockRouter.dismissTo).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});

it("a device_limit on re-enrolment opens the picker and retries enrolment with replaceDeviceId", async () => {
  const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  mockEnrol.mockRejectedValueOnce(limited(PHONES)).mockResolvedValueOnce({ account: { user_id: "u1" } });
  const tree = await render();
  await submit(tree);
  await act(async () => { button(tree, "notEnrolledConfirm").props.onClick(); });
  expect(title(tree)).toBe("deviceLimitTitle");

  await act(async () => { button(tree, "Old phone").props.onClick(); });
  const actions = alert.mock.calls[0][2] as Array<{ text: string; onPress?: () => void }>;
  await act(async () => { actions.find((a) => a.text === "deviceLimitConfirm")?.onPress?.(); });

  expect(mockSignIn).toHaveBeenCalledTimes(1);
  expect(mockEnrol).toHaveBeenCalledTimes(2);
  expect(mockEnrol.mock.calls[1].slice(0, 3)).toEqual(["https://example.org", "a@example.org", "pw"]);
  expect(mockEnrol.mock.calls[1][5]).toBe("d-old");
  expect(mockRouter.dismissTo).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});

it("a refused re-enrolment returns to the form with its message", async () => {
  mockEnrol.mockRejectedValueOnce(new ApiError(401, "invalid_credentials"));
  const tree = await render();
  await submit(tree);
  await act(async () => { button(tree, "notEnrolledConfirm").props.onClick(); });
  expect(title(tree)).toBe("signInTitle");
  expect(text(tree)).toContain("generic");
});
