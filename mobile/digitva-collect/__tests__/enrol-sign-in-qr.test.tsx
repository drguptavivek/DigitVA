/** Enrol screen: a scanned sign-in QR is confirmed, redeemed, and leads to PIN setup; every refusal is one message. */
import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const TOKEN = "SignInTokenSignInTokenSignInToken123";
const SERVER = "https://digitva.causeofdeathindia.com";
const mockRouter = { replace: jest.fn(), push: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockRedeem = jest.fn<Promise<{ user_id: string; name: string }>, unknown[]>();
const mockEnrol = jest.fn(async (..._args: unknown[]) => undefined);
const mockErrorText = jest.fn(() => "generic error");

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
  scan(tree, signInQr);
  expect(text(tree)).toContain("digitva.causeofdeathindia.com");
  expect(text(tree)).toContain("enrolConfirmSignInHint");
  expect(text(tree)).not.toContain("enrolConfirmProject");
  expect(mockRedeem).not.toHaveBeenCalled();
});

it("redeems on confirm, then goes to PIN setup through unlock with the refresh flag", async () => {
  mockRedeem.mockResolvedValue({ user_id: "u1", name: "Asha" });
  const tree = await render();
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
  mockRedeem.mockResolvedValue({ user_id: "coder1", name: "Coder" });
  const tree = await render();
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "coder1", refresh: "1" } });
});

it("treats a network failure as an ordinary error, not as an invalid QR", async () => {
  mockRedeem.mockRejectedValueOnce(new Error("network"));
  const tree = await render();
  scan(tree, signInQr);
  await press(tree, "enrolConfirm");
  expect(text(tree)).toContain("generic error");
  expect(text(tree)).not.toContain("errSignInQrInvalid");
});

it("rejects a sign-in QR for a server outside the allowed domain before anything is sent", async () => {
  const tree = await render();
  scan(tree, JSON.stringify({ v: 1, server: "https://evil.io", sign_in: TOKEN }));
  expect(text(tree)).toContain("errServerNotAllowed");
  expect(text(tree)).not.toContain(TOKEN);
  expect(mockRedeem).not.toHaveBeenCalled();
});

it("still enrols from an enrolment QR", async () => {
  const tree = await render();
  scan(tree, enrolQr);
  expect(text(tree)).toContain("enrolConfirmProject");
  await press(tree, "enrolConfirm");
  expect(mockEnrol).toHaveBeenCalledWith(SERVER, "AbCdEf123456_-x", "Pixel", "1.0.0");
  expect(mockRedeem).not.toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/");
});
