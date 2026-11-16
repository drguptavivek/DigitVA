/**
 * Device limit at sign-in (mobile-sign-in.md, replacing a phone at sign-in): a `409 device_limit` with `devices`
 * lists the phones; picking one asks first, then retries the same sign-in with `replace_device_id`; Cancel returns
 * to the form; an older server's reply without `devices` keeps the plain message.
 */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Alert, TextInput } from "react-native";

const mockRouter = { replace: jest.fn(), push: jest.fn(), dismissTo: jest.fn() };
const mockSignIn = jest.fn<Promise<{ user_id: string }>, unknown[]>();
const mockRecover = jest.fn<Promise<void>, unknown[]>();

let mockParams: Record<string, string> = {};
jest.mock("expo-router", () => ({ useRouter: () => mockRouter, useLocalSearchParams: () => mockParams }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ reload: async () => undefined, accounts: [], device: { server: "https://example.org" }, lockNow: async () => true }),
}));
jest.mock("../src/auth", () => ({
  signIn: (...args: unknown[]) => mockSignIn(...args),
  loadActiveSlot: async () => "active",
  loadDevice: async () => undefined,
  forgetDevice: async () => undefined,
  recoverSignOut: (...args: unknown[]) => mockRecover(...args),
  verifyPasswordForDelete: async () => undefined,
  WrongAccountError: class WrongAccountError extends Error {},
}));
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

const PHONES = [
  { device_id: "d-old", label: "Old phone", last_seen_at: "2026-11-01T10:00:00+00:00", unsent_count: 3 },
  { device_id: "d-two", label: "Second", last_seen_at: null, unsent_count: null },
  { device_id: "d-three", label: null, last_seen_at: null, unsent_count: 0 },
];
const limited = (devices?: unknown) =>
  new ApiError(409, "device_limit", undefined, undefined, devices === undefined ? { code: "device_limit" } : { code: "device_limit", devices });

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<SignIn />); });
  return tree;
}
const button = (tree: ReactTestRenderer, label: string) =>
  tree.root.find((node) => node.type === "button" && node.props["data-label"] === label);
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

async function submit(tree: ReactTestRenderer) {
  const [identifier, password] = tree.root.findAllByType(TextInput);
  await act(async () => { identifier.props.onChangeText("a@example.org"); });
  await act(async () => { password.props.onChangeText("pw"); });
  await act(async () => { button(tree, "signIn").props.onClick(); });
}

beforeEach(() => {
  mockParams = {};
  mockRecover.mockReset();
  mockSignIn.mockReset();
  mockRouter.dismissTo.mockReset();
});
afterEach(() => jest.restoreAllMocks());

it("lists the phones, confirms, then retries the same sign-in with replace_device_id", async () => {
  const alert = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  mockSignIn.mockRejectedValueOnce(limited(PHONES)).mockResolvedValueOnce({ user_id: "u1" });
  const tree = await render();
  await submit(tree);

  expect(tree.root.findByType("main").props.title).toBe("deviceLimitTitle");
  expect(text(tree)).toContain("deviceLimitBody");
  expect(button(tree, "Old phone")).toBeTruthy();
  expect(button(tree, "deviceLimitUnnamed")).toBeTruthy();
  expect(text(tree)).toContain('deviceLimitLastSeen{\\"time\\":\\"WHEN\\"}');
  // Only the phone with unsent items carries the warning, on its own attention row.
  expect(text(tree)).toContain('deviceLimitUnsent{\\"count\\":3}');
  expect(text(tree).match(/deviceLimitUnsent/g)).toHaveLength(1);
  expect(tree.root.findAll((node) => node.props["data-tone"] === "attention")).toHaveLength(1);

  await act(async () => { button(tree, "Old phone").props.onClick(); });
  expect(mockSignIn).toHaveBeenCalledTimes(1);
  const [title, body, actions] = alert.mock.calls[0] as [string, string, Array<{ text: string; onPress?: () => void }>];
  expect(title).toBe("deviceLimitConfirmTitle");
  expect(body).toContain("deviceLimitUnsent");
  await act(async () => { actions.find((a) => a.text === "deviceLimitConfirm")?.onPress?.(); });

  expect(mockSignIn).toHaveBeenCalledTimes(2);
  expect(mockSignIn.mock.calls[0][3]).toMatchObject({ replaceDeviceId: undefined });
  expect(mockSignIn.mock.calls[1].slice(0, 2)).toEqual(["a@example.org", "pw"]);
  expect(mockSignIn.mock.calls[1][3]).toMatchObject({ replaceDeviceId: "d-old" });
  expect(mockRouter.dismissTo).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
});

it("Cancel returns to the sign-in form without retrying", async () => {
  mockSignIn.mockRejectedValueOnce(limited(PHONES));
  const tree = await render();
  await submit(tree);
  expect(tree.root.findByType("main").props.title).toBe("deviceLimitTitle");

  await act(async () => { button(tree, "cancel").props.onClick(); });

  expect(tree.root.findByType("main").props.title).toBe("signInTitle");
  expect(mockSignIn).toHaveBeenCalledTimes(1);
});

it("an older server's device_limit without devices keeps the plain message", async () => {
  mockSignIn.mockRejectedValueOnce(limited());
  const tree = await render();
  await submit(tree);
  expect(tree.root.findByType("main").props.title).toBe("signInTitle");
  expect(text(tree)).toContain("deviceLimit");
  expect(text(tree)).not.toContain("deviceLimitTitle");
});

it("profile recovery keeps the plain message: it cannot retry with a phone signed out", async () => {
  mockParams = { userId: "u1", recover: "1" };
  mockRecover.mockRejectedValueOnce(limited(PHONES));
  const tree = await render();
  await submit(tree);
  expect(mockRecover).toHaveBeenCalledTimes(1);
  expect(tree.root.findByType("main").props.title).toBe("signInTitle");
  expect(text(tree)).toContain("deviceLimit");
  expect(text(tree)).not.toContain("deviceLimitTitle");
});

it("drops malformed phone entries and falls back when none is usable", async () => {
  const { deviceLimitPhones } = jest.requireActual("../src/DeviceLimitChoice") as typeof import("../src/DeviceLimitChoice");
  expect(deviceLimitPhones(limited([{ device_id: "ok", label: "A", last_seen_at: null, unsent_count: null }, { label: "no id" }, { device_id: "x", unsent_count: -1 }])))
    .toEqual([{ device_id: "ok", label: "A", last_seen_at: null, unsent_count: null }]);
  expect(deviceLimitPhones(limited([{ label: "no id" }]))).toBeUndefined();
  expect(deviceLimitPhones(limited("not a list"))).toBeUndefined();
  expect(deviceLimitPhones(new ApiError(409, "conflict", undefined, undefined, { devices: PHONES }))).toBeUndefined();
});
