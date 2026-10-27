import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockRouter = { replace: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockLockNow = jest.fn(async () => true);
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
const mockScreenLockEnabled = jest.fn(async () => false);
const mockScreenLockAvailable = jest.fn(async () => false);
const mockReadScreenLockPin = jest.fn<Promise<string | null>, []>(async () => null);
const mockEnableScreenLock = jest.fn(async () => undefined);
const mockOfferCount = jest.fn(async () => 0);
const mockNoteOffer = jest.fn(async () => undefined);
let mockCanUseBiometric = false;
let mockSlot: "active" | "demo" = "active";
const mockOrder: string[] = [];
const mockForgetDevice = jest.fn(async (..._args: unknown[]) => void mockOrder.push("forget"));
const mockStoredPinLength = jest.fn<Promise<number | null>, []>(async () => null);
const mockRecordPinLength = jest.fn(async (..._args: unknown[]) => undefined);
let mockParams: { userId?: string; refresh?: string; enableBiometric?: string; enableScreenLock?: string } = { userId: "u1", refresh: "1" };
let mockSignedOut = false;
const mockRedirect = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  Redirect: ({ href }: { href: unknown }) => {
    mockRedirect(href);
    return null;
  }
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: [mockSignedOut ? { ...mockAccount, needs_sign_in: true, signed_out: true } : mockAccount],
    reload: mockReload,
    lockNow: mockLockNow,
    unlocked: mockUnlocked
  })
}));
jest.mock("../src/auth", () => ({
  signIn: (...args: Parameters<typeof mockSignIn>) => mockSignIn(...args),
  forgetDevice: (...args: unknown[]) => mockForgetDevice(...args),
  loadActiveSlot: jest.fn(async () => mockSlot),
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
  screenLockEnabled: () => mockScreenLockEnabled(),
  screenLockAvailable: () => mockScreenLockAvailable(),
  readScreenLockPin: () => mockReadScreenLockPin(),
  enableScreenLock: (...args: unknown[]) => mockEnableScreenLock(...(args as [])),
  unlockOfferCount: () => mockOfferCount(),
  noteUnlockOffer: () => mockNoteOffer(),
  UNLOCK_OFFER_MAX: 2,
  PIN_MAX_LENGTH: 16,
  storedPinLength: () => mockStoredPinLength(),
  recordPinLength: (...args: unknown[]) => mockRecordPinLength(...args),
  WARN_AFTER_FAILURES: 3,
  WIPE_AFTER_FAILURES: 5,
  pinProblem: () => undefined
}));
jest.mock("expo-secure-store", () => ({ canUseBiometricAuthentication: () => mockCanUseBiometric }));
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
jest.mock("../src/nativeAuthLinks", () => ({
  mobileDigitsFromInput: (value: string) => value,
  nativeAuthUrl: () => "http://localhost:8051/vaauth/sign-in",
  NATIVE_AUTH_PATHS: { signIn: "sign-in", redeemCode: "redeem-code", forgotPassword: "forgot-password", passkeys: "passkeys" },
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

import { ApiError } from "../src/api";
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

/** The PIN boxes in order (one entry per box, whatever wrappers the renderer adds). */
function editableInputs(tree: ReturnType<typeof create>) {
  return tree.root.findAll(
    (node) => typeof node.props.onChangeText === "function" && String(node.props.testID).startsWith("pin-box-") && node.parent?.props.testID !== node.props.testID
  );
}

describe("native login refresh handoff", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockParams = { userId: "u1", refresh: "1" };
    mockSignedOut = false;
    mockSlot = "active";
    mockIsUnlocked.mockReturnValue(false);
    mockHasInterviewerStore.mockResolvedValue(true);
    mockBiometricEnabled.mockResolvedValue(false);
    mockScreenLockEnabled.mockResolvedValue(false);
    mockScreenLockAvailable.mockResolvedValue(false);
    mockReadScreenLockPin.mockResolvedValue(null);
    mockOfferCount.mockResolvedValue(0);
    mockCanUseBiometric = false;
    mockStoredPinLength.mockResolvedValue(null);
    mockUnlockInterviewer.mockResolvedValue({ ok: true });
    mockLockNow.mockClear();
    mockLockNow.mockImplementation(async () => {
      mockIsUnlocked.mockReturnValue(false);
      return true;
    });
  });

  it("passes refresh through after successful sign-in", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<SignIn />);
    });
    expect(tree!.root.findAllByProps({ "data-label": "passkeySignIn" })).toHaveLength(0);
    expect(tree!.root.findAllByProps({ accessibilityLabel: "otp" })).toHaveLength(0);
    act(() => input(tree!, "email")!.props.onChangeText("worker@example.org"));
    act(() => input(tree!, "password")!.props.onChangeText("secret"));
    await act(async () => tree!.root.findByProps({ "data-label": "signIn" }).props.onClick());
    expect(mockSignIn).toHaveBeenCalledWith("worker@example.org", "secret", "active");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  describe("a revoked device", () => {
    async function submitRevoked() {
      mockSignIn.mockImplementationOnce(async () => {
        // A switch lands while the request is out; the revoked device is still the pinned slot's.
        const slotAtStart = mockSlot;
        mockSlot = slotAtStart === "demo" ? "active" : "demo";
        throw new ApiError(403, "device_revoked");
      });
      let tree: ReturnType<typeof create>;
      await act(async () => {
        tree = create(<SignIn />);
      });
      act(() => input(tree!, "email")!.props.onChangeText("worker@example.org"));
      act(() => input(tree!, "password")!.props.onChangeText("secret"));
      await act(async () => tree!.root.findByProps({ "data-label": "signIn" }).props.onClick());
      await act(async () => tree!.unmount());
    }
    beforeEach(() => {
      mockOrder.length = 0;
      mockLockNow.mockImplementation(async () => {
        mockOrder.push("lock");
        return true;
      });
    });

    it("forgets the Demo device the sign-in used, after locking, since that returns the phone to Active", async () => {
      mockSlot = "demo";
      await submitRevoked();
      expect(mockSignIn).toHaveBeenCalledWith("worker@example.org", "secret", "demo");
      expect(mockForgetDevice).toHaveBeenCalledWith("demo");
      expect(mockOrder).toEqual(["lock", "forget"]);
    });

    it("keeps the Demo device when locking fails", async () => {
      mockSlot = "demo";
      mockLockNow.mockImplementation(async () => false);
      await submitRevoked();
      expect(mockForgetDevice).not.toHaveBeenCalled();
    });

    it("forgets the Active device the sign-in used without locking (the slot does not change)", async () => {
      mockSlot = "active";
      await submitRevoked();
      expect(mockForgetDevice).toHaveBeenCalledWith("active");
      expect(mockOrder).toEqual(["forget"]);
    });
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
    act(() => fields[6].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "pinSave" }).props.onClick());
    expect(mockCreateInterviewerDb).toHaveBeenCalledWith("u1", "123456");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("sends a signed-out profile to sign-in: no prompt, no PIN, nothing unlocked", async () => {
    mockSignedOut = true;
    mockParams = { userId: "u1", enableBiometric: "1" };
    mockBiometricEnabled.mockResolvedValue(true);
    mockReadBiometricPin.mockResolvedValue("123456" as never);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockRedirect).toHaveBeenCalledWith({ pathname: "/sign-in", params: { userId: "u1" } });
    expect(tree!.root.findAllByProps({ "data-label": "unlock" })).toHaveLength(0);
    expect(mockReadBiometricPin).not.toHaveBeenCalled();
    expect(mockHasInterviewerStore).not.toHaveBeenCalled();
    expect(mockUnlockInterviewer).not.toHaveBeenCalled();
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

  it("locks an already-open store before accepting a PIN for biometric opt-in", async () => {
    mockIsUnlocked.mockReturnValue(true);
    mockParams = { userId: "u1", enableBiometric: "1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockLockNow).toHaveBeenCalled();
    expect(mockEnableBiometric).toHaveBeenCalledWith("u1", "123456", "biometricPrompt");
    await act(async () => tree!.unmount());
  });

  it("refuses biometric enrollment if the existing store stays open", async () => {
    mockIsUnlocked.mockReturnValue(true);
    mockLockNow.mockImplementation(async () => false);
    mockParams = { userId: "u1", enableBiometric: "1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockEnableBiometric).not.toHaveBeenCalled();
    await act(async () => tree!.unmount());
  });

  it("shows a recoverable error when biometric state cannot be read", async () => {
    mockBiometricEnabled.mockRejectedValueOnce(new Error("secure store unavailable"));
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(tree!.root.findAll((node) => node.props.children === "errGeneric").length).toBeGreaterThan(0);
    await act(async () => tree!.unmount());
  });

  it("keeps the verified PIN unlock open when biometric enrollment fails", async () => {
    mockParams = { userId: "u1", enableBiometric: "1" };
    mockEnableBiometric.mockRejectedValueOnce(new Error("secure store unavailable"));
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockUnlocked).toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    expect(tree!.root.findAll((node) => node.props.children === "errGeneric").length).toBeGreaterThan(0);
    await act(async () => tree!.unmount());
  });

  it("unlocks with the phone screen lock when it is the only option on", async () => {
    mockScreenLockEnabled.mockResolvedValue(true);
    mockReadScreenLockPin.mockResolvedValue("654321");
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockReadScreenLockPin).toHaveBeenCalledTimes(1);
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "654321");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    await act(async () => tree!.unmount());
  });

  it("prefers the fingerprint prompt, and offers the screen lock as a button", async () => {
    mockBiometricEnabled.mockResolvedValue(true);
    mockScreenLockEnabled.mockResolvedValue(true);
    mockReadBiometricPin.mockResolvedValue(null);
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockReadBiometricPin).toHaveBeenCalled();
    expect(mockReadScreenLockPin).not.toHaveBeenCalled();
    mockReadScreenLockPin.mockResolvedValue("111111");
    await act(async () => tree!.root.findByProps({ "data-label": "screenLockEnable" }).props.onClick());
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "111111");
    await act(async () => tree!.unmount());
  });

  it("falls back to the PIN boxes when the screen-lock prompt is cancelled", async () => {
    mockScreenLockEnabled.mockResolvedValue(true);
    mockReadScreenLockPin.mockRejectedValue(new Error("screen_lock_refused"));
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(mockUnlockInterviewer).not.toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalled();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "123456");
    await act(async () => tree!.unmount());
  });

  it("turns the screen lock on after the PIN is checked when Settings asked for it", async () => {
    mockParams = { userId: "u1", enableScreenLock: "1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockEnableScreenLock).toHaveBeenCalledWith("u1", "123456", "screenLockPrompt");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    await act(async () => tree!.unmount());
  });

  it("keeps the PIN rules: a wrong PIN clears the boxes, and the Unlock button needs all six digits", async () => {
    mockParams = { userId: "u1" };
    mockUnlockInterviewer.mockResolvedValueOnce({ ok: false, wipe: false, failures: 1 } as never);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("12345"));
    expect(tree!.root.findByProps({ "data-label": "unlock" }).props.disabled).toBe(true);
    act(() => editableInputs(tree!)[5].props.onChangeText("6"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "123456");
    expect(editableInputs(tree!).every((box) => box.props.value === "")).toBe(true);
    await act(async () => tree!.unmount());
  });

  it("offers fingerprint and screen lock after PIN setup, and turns the screen lock on", async () => {
    mockCanUseBiometric = true;
    mockScreenLockAvailable.mockResolvedValue(true);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<PinSetup />);
    });
    const fields = editableInputs(tree!);
    act(() => fields[0].props.onChangeText("123456"));
    act(() => fields[6].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "pinSave" }).props.onClick());
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(mockNoteOffer).toHaveBeenCalledTimes(1);
    await act(async () => tree!.root.findByProps({ "data-label": "screenLockEnable" }).props.onClick());
    expect(mockEnableScreenLock).toHaveBeenCalledWith("u1", "123456", "screenLockPrompt");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("lets the first-run offer be skipped", async () => {
    mockCanUseBiometric = true;
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<PinSetup />);
    });
    const fields = editableInputs(tree!);
    act(() => fields[0].props.onChangeText("123456"));
    act(() => fields[6].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "pinSave" }).props.onClick());
    await act(async () => tree!.root.findByProps({ "data-label": "biometricSkip" }).props.onClick());
    expect(mockEnableBiometric).not.toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", refresh: "1" } });
    await act(async () => tree!.unmount());
  });

  it("re-offers once on a later PIN unlock, not when already offered twice or an option is on", async () => {
    mockCanUseBiometric = true;
    mockParams = { userId: "u1" };
    mockOfferCount.mockResolvedValue(1);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockRouter.replace).not.toHaveBeenCalled();
    await act(async () => tree!.root.findByProps({ "data-label": "biometricEnable" }).props.onClick());
    expect(mockEnableBiometric).toHaveBeenCalledWith("u1", "123456", "biometricPrompt");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    await act(async () => tree!.unmount());

    jest.clearAllMocks();
    mockOfferCount.mockResolvedValue(2);
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    act(() => editableInputs(tree!)[0].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1" } });
    await act(async () => tree!.unmount());
  });

  const longField = (tree: ReturnType<typeof create>) =>
    tree.root.findAll((node) => typeof node.props.onChangeText === "function" && node.props.maxLength === 16 && node.parent?.props.maxLength !== 16)[0];

  it("shows the long-PIN link beside the boxes when the length is unknown, and unlocks a 7-digit PIN untruncated", async () => {
    mockParams = { userId: "u1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(editableInputs(tree!)).toHaveLength(6);
    expect(longField(tree!)).toBeUndefined();
    act(() => tree!.root.findAll((n) => n.props.accessibilityRole === "link" && typeof n.props.onPress === "function")[0].props.onPress());
    expect(editableInputs(tree!)).toHaveLength(0);
    act(() => longField(tree!).props.onChangeText("1234567"));
    expect(tree!.root.findByProps({ "data-label": "unlock" }).props.disabled).toBe(false);
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "1234567");
    await act(async () => tree!.unmount());
  });

  it("opens directly in the long-PIN field when the stored length is above six, and keeps Unlock off below six digits", async () => {
    mockParams = { userId: "u1" };
    mockStoredPinLength.mockResolvedValue(8);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(editableInputs(tree!)).toHaveLength(0);
    act(() => longField(tree!).props.onChangeText("12345"));
    expect(tree!.root.findByProps({ "data-label": "unlock" }).props.disabled).toBe(true);
    act(() => longField(tree!).props.onChangeText("12345678"));
    await act(async () => tree!.root.findByProps({ "data-label": "unlock" }).props.onClick());
    expect(mockUnlockInterviewer).toHaveBeenCalledWith("u1", "12345678");
    await act(async () => tree!.unmount());
  });

  it("opens in the boxes when the stored length is six", async () => {
    mockParams = { userId: "u1" };
    mockStoredPinLength.mockResolvedValue(6);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Unlock />);
    });
    await settle();
    expect(editableInputs(tree!)).toHaveLength(6);
    await act(async () => tree!.unmount());
  });

  it("records the PIN length at setup", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<PinSetup />);
    });
    const fields = editableInputs(tree!);
    act(() => fields[0].props.onChangeText("123456"));
    act(() => fields[6].props.onChangeText("123456"));
    await act(async () => tree!.root.findByProps({ "data-label": "pinSave" }).props.onClick());
    expect(mockRecordPinLength).toHaveBeenCalledWith("u1", 6);
    await act(async () => tree!.unmount());
  });
});
