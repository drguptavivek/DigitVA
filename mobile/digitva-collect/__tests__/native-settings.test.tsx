/** Native Settings: its sections, the enrolled server (read-only, changed only by re-enrolling), and the actions each section keeps. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockLockNow = jest.fn(async () => true);
const mockChooseLocale = jest.fn(async () => undefined);
const mockConfirm = jest.fn<Promise<void>, [unknown[], () => void]>(async () => undefined);
const mockReEnrol = jest.fn<Promise<void>, [unknown[]]>(async () => undefined);
const mockExport = jest.fn(async () => 4);
const mockToast = jest.fn();
let mockBiometricAvailable = true;
const mockAccounts: Array<{ user_id: string; name: string; signed_out?: boolean; needs_sign_in?: boolean }> = [{ user_id: "a", name: "Asha" }];
const mockSwitchSlot = jest.fn(async (_slot: string) => true);
let mockSlot = "active";

jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-secure-store", () => ({ canUseBiometricAuthentication: () => mockBiometricAvailable }));
jest.mock("react-native-safe-area-context", () => ({ SafeAreaView: "SafeAreaView", useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    device: { device_id: "dev-1", server: "https://digitvav3.causeofdeathindia.com", project_id: "P", project_name: "Project" },
    accounts: mockAccounts,
    uiLocale: "en",
    chooseUiLocale: mockChooseLocale,
    lockNow: mockLockNow,
    reload: mockReload,
    slot: mockSlot,
    switchSlot: mockSwitchSlot,
  }),
}));
let mockScreenLockOn = false;
let mockScreenLockPossible = true;
const mockTurnOffScreenLock = jest.fn(async (_userId: string) => undefined);
jest.mock("../src/vault", () => ({
  biometricEnabled: async () => false,
  screenLockEnabled: async () => mockScreenLockOn,
  screenLockAvailable: async () => mockScreenLockPossible,
  turnOffBiometric: jest.fn(async () => undefined),
  turnOffScreenLock: (userId: string) => mockTurnOffScreenLock(userId),
}));
jest.mock("../src/errorExport", () => ({ exportErrors: () => mockExport() }));
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("../src/reEnrolConfirm", () => ({
  confirmReEnrol: (accounts: unknown[], onConfirmed: () => void) => mockConfirm(accounts, onConfirmed),
  reEnrolDevice: (accounts: unknown[]) => mockReEnrol(accounts),
}));

import NativeSettings from "../src/nativeRoutes/settings";
import { ShellContext, type Shell } from "../src/nativeShell/shellContext";

const shell: Shell = {
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "a",
  sync: { work: { unsent: 2, attention: 0, inProgress: 1, items: [] }, lastAt: new Date(2026, 9, 23, 9, 7).getTime(), busy: false, result: undefined, offline: false },
  sendNow: jest.fn(async () => undefined), recount: jest.fn(async () => undefined), refreshNow: jest.fn(async () => undefined), header: true, tabs: true,
};

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<ShellContext.Provider value={shell}><NativeSettings /></ShellContext.Provider>); });
  return tree;
}
const pressLabel = async (tree: ReactTestRenderer, label: string) => {
  const target = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
  expect(target).toBeDefined();
  await act(async () => { await target.props.onPress(); });
};
const out = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => {
  jest.clearAllMocks();
  mockBiometricAvailable = true;
  mockScreenLockOn = false;
  mockScreenLockPossible = true;
  mockSlot = "active";
});

it("is titled Settings and shows every section", async () => {
  const tree = await render();
  const text = out(tree);
  for (const heading of ["Settings", "Account", "Active or demo", "Language", "Security", "Sync", "Help & support", "About"]) expect(text).toContain(`"${heading}"`);
  expect(text).toContain("https://digitvav3.causeofdeathindia.com");
  expect(text).toContain("dev-1");
  expect(text).toContain("Synced 09:07");
  expect(text).toContain("2 ready to send from this phone");
  expect(text).toContain("The app locks after 5 minutes without use.");
  expect(text).toContain("Version ");
});

it("puts Change server / re-enrol last, and re-enrols through the unsent-work check", async () => {
  const tree = await render();
  const buttons = tree.root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel);
  expect(buttons.at(-1)?.props.accessibilityLabel).toBe("Change server / re-enrol");
  await pressLabel(tree, "Change server / re-enrol");
  expect(mockConfirm).toHaveBeenCalledWith(mockAccounts, expect.any(Function));
  expect(mockReEnrol).not.toHaveBeenCalled();
  await act(async () => mockConfirm.mock.calls[0][1]());
  expect(mockReEnrol).toHaveBeenCalledWith(mockAccounts);
  expect(mockReload).toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenCalledWith("/enrol");
});

it("keeps the app language choice, fingerprint enabling and the Home button", async () => {
  const tree = await render();
  await pressLabel(tree, "हिन्दी");
  expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  await pressLabel(tree, "Use fingerprint: Asha");
  expect(mockLockNow).toHaveBeenCalled();
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "a", enableBiometric: "1" } });
  await pressLabel(tree, "Home");
  expect(mockRouter.back).toHaveBeenCalled();
});

it("offers no fingerprint button on a phone without biometrics", async () => {
  mockBiometricAvailable = false;
  expect(out(await render())).not.toContain("Use fingerprint");
});

it("sends now from the Sync section and opens Help from Help & support", async () => {
  const tree = await render();
  await pressLabel(tree, "Send now");
  expect(shell.sendNow).toHaveBeenCalled();
  await pressLabel(tree, "Help guide");
  expect(shell.openSheet).toHaveBeenCalledWith("help");
});

it("exports errors and says how many entries were shared, or that there are none", async () => {
  const tree = await render();
  await pressLabel(tree, "Export errors");
  expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "Shared 4 error entries." });
  mockExport.mockResolvedValueOnce(0);
  await pressLabel(tree, "Export errors");
  expect(mockToast).toHaveBeenLastCalledWith({ kind: "info", text: "No errors recorded." });
  mockExport.mockRejectedValueOnce(new Error("share failed"));
  await pressLabel(tree, "Export errors");
  expect(mockToast.mock.calls.at(-1)?.[0]).toMatchObject({ kind: "error" });
});

it("turns the phone screen lock on through the PIN screen, and off again", async () => {
  const tree = await render();
  await pressLabel(tree, "Use phone screen lock: Asha");
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "a", enableScreenLock: "1" } });
  mockScreenLockOn = true;
  const on = await render();
  expect(out(on)).toContain("Phone screen lock unlock is on");
  await pressLabel(on, "Turn off phone screen lock: Asha");
  expect(mockTurnOffScreenLock).toHaveBeenCalledWith("a");
});

it("offers neither fingerprint nor screen lock for a signed-out profile: its PIN alone must not open it", async () => {
  mockAccounts.push({ user_id: "s", name: "Sita", signed_out: true, needs_sign_in: true });
  try {
    const text = out(await render());
    expect(text).toContain("Use fingerprint: Asha");
    expect(text).toContain("Use phone screen lock: Asha");
    expect(text).not.toContain("Use fingerprint: Sita");
    expect(text).not.toContain("Use phone screen lock: Sita");
  } finally {
    mockAccounts.pop();
  }
});

it("offers no screen-lock button on a phone without a screen lock", async () => {
  mockScreenLockPossible = false;
  expect(out(await render())).not.toContain("Use phone screen lock");
});

it("switches to Demo from the Active or demo section, and does nothing for the slot already in use", async () => {
  const tree = await render();
  const kind = (label: string) => tree.root.findAll((n) => n.props.label === label && n.props.kind)[0]?.props.kind;
  expect(kind("Active")).toBe("primary");
  expect(kind("Demo")).toBe("secondary");
  await pressLabel(tree, "Active");
  expect(mockSwitchSlot).not.toHaveBeenCalled();
  // switchSlot itself opens Try the demo when there is no demo enrolment (__tests__/slot-switch.test.tsx).
  await pressLabel(tree, "Demo");
  expect(mockSwitchSlot).toHaveBeenCalledWith("demo");
});

it("shows an error when the switch could not save open work", async () => {
  mockSwitchSlot.mockResolvedValueOnce(false);
  const tree = await render();
  await pressLabel(tree, "Demo");
  expect(mockSwitchSlot).toHaveBeenCalledWith("demo");
  expect(out(tree)).toContain("Something went wrong. Try again.");
});

it("re-enrols the demo slot through Try the demo, not QR enrolment", async () => {
  mockSlot = "demo";
  const tree = await render();
  await pressLabel(tree, "Change server / re-enrol");
  await act(async () => mockConfirm.mock.calls[0][1]());
  expect(mockRouter.replace).toHaveBeenCalledWith("/demo");
});
