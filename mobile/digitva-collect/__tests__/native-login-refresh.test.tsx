import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockRouter = { replace: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockUnlocked = jest.fn();
const mockSignIn = jest.fn(async () => mockAccount);
const mockUnlockInterviewer = jest.fn(async () => ({ ok: true as const }));
const mockCreateInterviewerDb = jest.fn(async () => undefined);
const mockHasInterviewerStore = jest.fn(async () => true);
const mockIsUnlocked = jest.fn(() => false);
const mockFailedAttempts = jest.fn(async () => 0);
const mockBiometricEnabled = jest.fn(async () => false);
const mockReadBiometricPin = jest.fn(async () => null);
const mockEnableBiometric = jest.fn(async () => undefined);
let mockParams: { userId?: string; refresh?: string } = { userId: "u1", refresh: "1" };

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Redirect: () => null
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: [mockAccount],
    reload: mockReload,
    unlocked: mockUnlocked
  })
}));
jest.mock("../src/auth", () => ({
  signIn: (...args: Parameters<typeof mockSignIn>) => mockSignIn(...args),
  forgetDevice: jest.fn(),
  loadDevice: jest.fn(async () => ({ server: "http://localhost:8051" })),
  unlockInterviewer: (...args: Parameters<typeof mockUnlockInterviewer>) => mockUnlockInterviewer(...args)
}));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => mockIsUnlocked(),
  hasInterviewerStore: () => mockHasInterviewerStore(),
  createInterviewerDb: (...args: Parameters<typeof mockCreateInterviewerDb>) => mockCreateInterviewerDb(...args)
}));
jest.mock("../src/vault", () => ({
  biometricEnabled: (...args: Parameters<typeof mockBiometricEnabled>) => mockBiometricEnabled(...args),
  failedAttempts: (...args: Parameters<typeof mockFailedAttempts>) => mockFailedAttempts(...args),
  readBiometricPin: (...args: Parameters<typeof mockReadBiometricPin>) => mockReadBiometricPin(...args),
  enableBiometric: (...args: Parameters<typeof mockEnableBiometric>) => mockEnableBiometric(...args),
  WARN_AFTER_FAILURES: 3,
  WIPE_AFTER_FAILURES: 5,
  pinProblem: () => undefined
}));
jest.mock("expo-secure-store", () => ({ canUseBiometricAuthentication: () => false }));
jest.mock("../src/api", () => ({ ApiError: class ApiError extends Error {} }));
jest.mock("../src/nativeAuthLinks", () => ({
  mobileDigitsFromInput: (value: string) => value,
  nativeAuthUrl: () => "http://localhost:8051/vaauth/sign-in",
  NATIVE_AUTH_PATHS: { signIn: "sign-in", redeemCode: "redeem-code", forgotPassword: "forgot-password" },
  normalizeMobileIdentifier: (value: string) => value
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      ReactActual.createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    Row: ({ children }: { children: ReactNode }) => ReactActual.createElement("div", null, children),
    Screen: ({ children }: { children: ReactNode }) => ReactActual.createElement("main", null, children),
    errorText: () => "error",
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, input: {}, phoneInputRow: {}, phonePrefix: {}, phoneInput: {}, authLinks: {} })
  };
});

import SignIn from "../src/nativeRoutes/sign-in";
import Unlock from "../src/nativeRoutes/unlock";
import PinSetup from "../src/nativeRoutes/pin-setup";

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function input(tree: ReturnType<typeof create>, label: string) {
  return tree.root.findAllByProps({ accessibilityLabel: label }).find((node) => typeof node.props.onChangeText === "function");
}

function editableInputs(tree: ReturnType<typeof create>) {
  return tree.root.findAll((node) => typeof node.props.onChangeText === "function");
}

describe("native login refresh handoff", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = { userId: "u1", refresh: "1" };
    mockIsUnlocked.mockReturnValue(false);
    mockHasInterviewerStore.mockResolvedValue(true);
    mockBiometricEnabled.mockResolvedValue(false);
    mockUnlockInterviewer.mockResolvedValue({ ok: true });
  });

  it("passes refresh through after successful sign-in", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<SignIn />);
    });
    act(() => input(tree!, "email")!.props.onChangeText("worker@example.org"));
    act(() => input(tree!, "password")!.props.onChangeText("secret"));
    await act(async () => tree!.root.findByProps({ "data-label": "signIn" }).props.onClick());
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("preserves refresh when an already-unlocked account redirects", async () => {
    mockIsUnlocked.mockReturnValue(true);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("preserves refresh when an account without a store goes to PIN setup", async () => {
    mockHasInterviewerStore.mockResolvedValue(false);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/pin-setup", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("preserves refresh after PIN setup completes", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<PinSetup />);
    });
    const fields = editableInputs(tree!);
    act(() => fields[0].props.onChangeText("123456"));
    act(() => fields[1].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "pinSave" }).props.onClick());
    expect(mockCreateInterviewerDb).toHaveBeenCalledWith("u1", "123456");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("does not add a refresh flag to an ordinary PIN unlock", async () => {
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    await act(async () => tree!.unmount());
  });
});
