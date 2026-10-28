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
let mockPlay = false;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => false, isPlayDistribution: () => mockPlay }));
const mockCheckForUpdate = jest.fn(async (_server?: string) => ({ status: "available", version: "9.9.9", url: "https://example.org/digitva.apk" }));
jest.mock("../src/updateCheck", () => ({ checkForUpdate: (server?: string) => mockCheckForUpdate(server) }));
const mockOpenURL = jest.fn(async (_url: string) => undefined);
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
const mockDeleteDemo = jest.fn(async (_userId: string, _password: string) => undefined);
const mockRequestDeletion = jest.fn(async (_userId: string) => undefined);
const mockDevices = [
  { device_id: "11111111-1111-4111-8111-111111111111", name: "This phone", platform: "android", app_version: "0.3.11", enrolled_at: "2026-10-20T00:00:00Z", last_seen_at: "2026-10-28T00:00:00Z", current: true },
  { device_id: "22222222-2222-4222-8222-222222222222", name: "Other phone", platform: "android", app_version: "0.3.10", enrolled_at: "2026-10-19T00:00:00Z", last_seen_at: "2026-10-27T00:00:00Z", current: false },
];
const mockListMyDevices = jest.fn(async (_userId: string) => mockDevices);
const mockDecommissionMyDevice = jest.fn(async (_userId: string, deviceId: string) => ({ decommissioned: true, sessions_ended: 1, current: deviceId === mockDevices[0].device_id }));
const mockRefreshAccessSummary = jest.fn(async (_userId: string) => ({
  user: { user_id: "a", name: "Asha" },
  is_admin: false,
  roles: ["interviewer", "coder"],
  demo_coding: { available: false, project_ids: [] },
  projects: [{
    project_id: "P",
    project_name: "Project",
    has_tree: false,
    grants: [{ role: "coder", scope: "project", active: true, source: "assigned", codes: true }],
    sites: [],
    actions: { interview: [{ site_id: "S", site_name: "Site", web_intake_mode: "direct", org_units: [] }], register_death: [] },
  }],
}));
jest.mock("../src/auth", () => ({
  deleteDemoAccount: (userId: string, password: string) => mockDeleteDemo(userId, password),
  requestAccountDeletion: (userId: string) => mockRequestDeletion(userId),
  listMyDevices: (userId: string) => mockListMyDevices(userId),
  decommissionMyDevice: (userId: string, deviceId: string) => mockDecommissionMyDevice(userId, deviceId),
  refreshAccessSummary: (userId: string) => mockRefreshAccessSummary(userId),
}));
const mockReadDevicePermissions = jest.fn(async () => ({
  camera: { granted: false, canAskAgain: true },
  microphone: { granted: false, canAskAgain: true },
}));
const mockRequestDevicePermission = jest.fn(async (_name: string) => ({ granted: true, canAskAgain: true }));
jest.mock("../src/devicePermissions.native", () => ({
  readDevicePermissions: () => mockReadDevicePermissions(),
  requestDevicePermission: (name: string) => mockRequestDevicePermission(name),
}));
jest.mock("../src/reEnrolConfirm", () => ({
  confirmReEnrol: (accounts: unknown[], onConfirmed: () => void) => mockConfirm(accounts, onConfirmed),
  reEnrolDevice: (accounts: unknown[]) => mockReEnrol(accounts),
}));

import { Alert, Linking } from "react-native";

import { ApiError } from "../src/api";
import en from "../src/strings/en.json";
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
  mockPlay = false;
  mockReadDevicePermissions.mockReset();
  mockReadDevicePermissions.mockResolvedValue({
    camera: { granted: false, canAskAgain: true },
    microphone: { granted: false, canAskAgain: true },
  });
  mockRequestDevicePermission.mockReset();
  mockRequestDevicePermission.mockResolvedValue({ granted: true, canAskAgain: true });
  mockListMyDevices.mockReset();
  mockListMyDevices.mockResolvedValue(mockDevices);
  mockDecommissionMyDevice.mockReset();
  mockDecommissionMyDevice.mockImplementation(async (_userId: string, deviceId: string) => ({ decommissioned: true, sessions_ended: 1, current: deviceId === mockDevices[0].device_id }));
  mockRefreshAccessSummary.mockClear();
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

it("checks camera and microphone status on mount without prompting", async () => {
  const tree = await render();
  expect(mockReadDevicePermissions).toHaveBeenCalledTimes(1);
  expect(mockRequestDevicePermission).not.toHaveBeenCalled();
  expect(out(tree)).toContain(en.permissionsEnableCamera);
  expect(out(tree)).toContain(en.permissionsEnableMicrophone);
});

it("requests a device permission only after its explicit enable action", async () => {
  const tree = await render();
  expect(mockRequestDevicePermission).not.toHaveBeenCalled();
  await pressLabel(tree, en.permissionsEnableCamera);
  expect(mockRequestDevicePermission).toHaveBeenCalledWith("camera");
});

it("offers phone settings when a device permission cannot be requested again", async () => {
  mockReadDevicePermissions.mockResolvedValueOnce({
    camera: { granted: false, canAskAgain: false },
    microphone: { granted: true, canAskAgain: false },
  });
  const openSettings = jest.spyOn(Linking, "openSettings").mockResolvedValue(undefined);
  try {
    const tree = await render();
    await pressLabel(tree, en.permissionsOpenSettings);
    expect(openSettings).toHaveBeenCalled();
    expect(mockRequestDevicePermission).not.toHaveBeenCalled();
  } finally {
    openSettings.mockRestore();
  }
});

it("refreshes cached project access through the explicit permissions check", async () => {
  const tree = await render();
  await pressLabel(tree, en.permissionsCheck);
  expect(mockRefreshAccessSummary).toHaveBeenCalledWith("a");
  expect(mockReload).toHaveBeenCalled();
  expect(out(tree)).toContain(en.permissionsProject.replace("{project}", "Project"));
});

it("lists devices and removes another phone by refreshing only the device list", async () => {
  const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  mockListMyDevices.mockResolvedValueOnce(mockDevices).mockResolvedValueOnce([mockDevices[0]]);
  try {
    const tree = await render();
    const removeButtons = tree.root.findAll((node) => node.props.accessibilityLabel === en.deviceDecommission && typeof node.props.onPress === "function");
    expect(removeButtons).toHaveLength(2);
    expect(out(tree)).toContain(en.devicesCount.replace("{count}", "2"));
    await act(async () => { removeButtons[1].props.onPress(); });
    const confirm = (alertSpy.mock.calls.at(-1)?.[2] as Array<{ text: string; onPress?: () => void }>).find((button) => button.text === en.deviceDecommission);
    await act(async () => { confirm?.onPress?.(); });
    expect(mockDecommissionMyDevice).toHaveBeenCalledWith("a", mockDevices[1].device_id);
    expect(mockReload).not.toHaveBeenCalled();
    expect(mockListMyDevices).toHaveBeenCalledTimes(2);
    expect(out(tree)).not.toContain("Other phone");
  } finally {
    alertSpy.mockRestore();
  }
});

it("confirms current-phone removal, locks first, and reloads without wiping local data", async () => {
  const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  try {
    const tree = await render();
    const remove = tree.root.findAll((node) => node.props.accessibilityLabel === en.deviceDecommission && typeof node.props.onPress === "function")[0];
    await act(async () => { remove.props.onPress(); });
    expect((alertSpy.mock.calls.at(-1)?.[1] as string)).toBe(en.deviceDecommissionConfirm);
    const confirm = (alertSpy.mock.calls.at(-1)?.[2] as Array<{ text: string; onPress?: () => void }>).find((button) => button.text === en.deviceDecommission);
    await act(async () => { confirm?.onPress?.(); });
    expect(mockLockNow).toHaveBeenCalled();
    expect(mockDecommissionMyDevice).toHaveBeenCalledWith("a", mockDevices[0].device_id);
    expect(mockReload).toHaveBeenCalled();
  } finally {
    alertSpy.mockRestore();
  }
});

it("shows a retryable device-list error", async () => {
  mockListMyDevices.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(mockDevices);
  const tree = await render();
  expect(out(tree)).toContain(en.devicesRetry);
  await pressLabel(tree, en.devicesRetry);
  expect(mockListMyDevices).toHaveBeenCalledTimes(2);
  expect(out(tree)).toContain("Other phone");
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

it("sideloaded build: checks for updates and offers the hosted APK download", async () => {
  const openURL = jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);
  try {
    const tree = await render();
    expect(out(tree)).not.toContain("App updates come from Google Play.");
    await pressLabel(tree, "Check for updates");
    expect(mockCheckForUpdate).toHaveBeenCalledWith("https://digitvav3.causeofdeathindia.com");
    expect(out(tree)).toContain("Update available: 9.9.9");
    await pressLabel(tree, "Download");
    expect(mockOpenURL).toHaveBeenCalledWith("https://example.org/digitva.apk");
  } finally {
    openURL.mockRestore();
  }
});

it("Google Play build: says updates come from Google Play, with no update check or Download", async () => {
  mockPlay = true;
  const tree = await render();
  const text = out(tree);
  expect(text).toContain("About");
  expect(text).toContain("App updates come from Google Play.");
  expect(text).not.toContain("Check for updates");
  expect(text).not.toContain("Download");
  expect(mockCheckForUpdate).not.toHaveBeenCalled();
});

it("re-enrols the demo slot through Try the demo, not QR enrolment", async () => {
  mockSlot = "demo";
  const tree = await render();
  await pressLabel(tree, "Change server / re-enrol");
  await act(async () => mockConfirm.mock.calls[0][1]());
  expect(mockRouter.replace).toHaveBeenCalledWith("/demo");
});

describe("Delete my account and the privacy links", () => {
  let alertSpy: jest.SpyInstance;
  /** Press the Alert button labelled `text` from the latest Alert.alert call. */
  const pressAlert = async (text: string) => {
    const buttons = alertSpy.mock.calls.at(-1)?.[2] as Array<{ text: string; onPress?: () => void }>;
    const button = buttons.find((b) => b.text === text);
    expect(button).toBeDefined();
    await act(async () => { button?.onPress?.(); });
  };
  const typePassword = async (tree: ReactTestRenderer, value: string) => {
    const input = tree.root.findAll((n) => n.props.accessibilityLabel === "Password" && typeof n.props.onChangeText === "function")[0];
    expect(input).toBeDefined();
    await act(async () => { input.props.onChangeText(value); });
  };
  beforeEach(() => {
    alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  });
  afterEach(() => alertSpy.mockRestore());

  it("links to the privacy policy and the data-requests page on the enrolled server", async () => {
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    const tree = await render();
    await pressLabel(tree, "Privacy policy");
    await pressLabel(tree, "Consent and data requests");
    expect(open.mock.calls.map(([url]) => url)).toEqual([
      "https://digitvav3.causeofdeathindia.com/privacy",
      "https://digitvav3.causeofdeathindia.com/data-requests",
    ]);
    open.mockRestore();
  });

  it("sends a staff account's request after a confirmation and shows Request sent", async () => {
    const tree = await render();
    expect(out(tree)).toContain(en.deleteAccountStaffNote);
    await pressLabel(tree, "Delete my account");
    expect(alertSpy.mock.calls[0][1]).toBe(en.deleteAccountStaffConfirm);
    expect(mockRequestDeletion).not.toHaveBeenCalled();
    await pressAlert("Send request");
    expect(mockRequestDeletion).toHaveBeenCalledWith("a");
    expect(mockDeleteDemo).not.toHaveBeenCalled();
    expect(out(tree)).toContain(en.deleteAccountRequestSent);
  });

  it("deletes a demo account after the password and a confirmation, then reloads to Home", async () => {
    mockSlot = "demo";
    const tree = await render();
    expect(out(tree)).toContain(en.deleteAccountDemoNote);
    await pressLabel(tree, "Delete my account");
    expect(alertSpy).not.toHaveBeenCalled();  // first the password field
    await typePassword(tree, "correct horse battery");
    await pressLabel(tree, "Delete my account");
    expect(alertSpy.mock.calls[0][1]).toBe(en.deleteAccountDemoConfirm);
    expect(mockDeleteDemo).not.toHaveBeenCalled();
    await pressAlert("Delete");
    expect(mockLockNow).toHaveBeenCalled();
    expect(mockDeleteDemo).toHaveBeenCalledWith("a", "correct horse battery");
    expect(mockRequestDeletion).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: en.deleteAccountDone });
    expect(mockReload).toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
  });

  it.each([
    [new ApiError(400, "wrong_password"), en.deleteAccountWrongPassword],
    [new ApiError(409, "deletion_refused", undefined, undefined, { reason: "shared_case" }), en.deleteAccountRefusedShared],
  ])("shows the refusal and stays on Settings", async (refusal, text) => {
    mockSlot = "demo";
    mockDeleteDemo.mockRejectedValueOnce(refusal);
    const tree = await render();
    await pressLabel(tree, "Delete my account");
    await typePassword(tree, "pw");
    await pressLabel(tree, "Delete my account");
    await pressAlert("Delete");
    expect(out(tree)).toContain(text);
    expect(mockRouter.replace).not.toHaveBeenCalled();
  });

  it("offers no deletion for a signed-out profile: it has no session to ask with", async () => {
    mockAccounts[0].signed_out = true;
    try {
      expect(out(await render())).not.toContain("Delete my account");
    } finally {
      delete mockAccounts[0].signed_out;
    }
  });
});
