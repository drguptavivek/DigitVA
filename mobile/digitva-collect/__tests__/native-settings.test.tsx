/** Native Settings: its sections, the enrolled server (read-only, changed only by re-enrolling), and the actions each section keeps. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import type { UpdateResult } from "../src/updateCheck";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn() };
const mockReload = jest.fn(async () => undefined);
const mockLockNow = jest.fn(async () => true);
const mockChooseLocale = jest.fn(async () => undefined);
const mockConfirm = jest.fn<Promise<void>, [unknown[], () => void]>(async () => undefined);
const mockReEnrol = jest.fn<Promise<void>, [unknown[]]>(async () => undefined);
const mockExport = jest.fn(async () => 4);
const mockToast = jest.fn();
let mockBiometricAvailable = true;
let mockAndroidPackage: string | undefined = "com.causeofdeathindia.digitvacollect";
const mockSecureStoreValues = new Map<string, string>();
const mockSecureStoreSet = jest.fn(async (key: string, value: string) => { mockSecureStoreValues.set(key, value); });
const mockAccounts: Array<{ user_id: string; name: string; standalone?: boolean; signed_out?: boolean; needs_sign_in?: boolean; offline_coding_access?: string[] }> = [{ user_id: "a", name: "Asha" }];
const mockSwitchSlot = jest.fn(async (_slot: string) => true);
let mockSlot = "active";

jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-constants", () => ({ __esModule: true, default: { expoConfig: { android: { get package() { return mockAndroidPackage; } } } } }));
jest.mock("expo-secure-store", () => ({
  canUseBiometricAuthentication: () => mockBiometricAvailable,
  getItemAsync: jest.fn(async (key: string) => mockSecureStoreValues.get(key) ?? null),
  setItemAsync: (key: string, value: string) => mockSecureStoreSet(key, value),
}));
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
let mockPlus = false;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus, isPlayDistribution: () => mockPlay }));
const mockCheckForUpdate = jest.fn<Promise<UpdateResult>, [server?: string]>(async (_server?: string) => ({ status: "available", version: "9.9.9", url: "https://example.org/digitva.apk" }));
const mockCheckServerCompatibility = jest.fn(async (_server: string) => ({ status: "compatible", buildRevision: "abcdef0123456789abcdef0123456789abcdef01" }));
jest.mock("../src/updateCheck", () => ({ checkForUpdate: (server?: string) => mockCheckForUpdate(server), checkServerCompatibility: (server: string) => mockCheckServerCompatibility(server) }));
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
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "a", server: "https://digitvav3.causeofdeathindia.com",
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
  mockAndroidPackage = "com.causeofdeathindia.digitvacollect";
  mockScreenLockOn = false;
  mockScreenLockPossible = true;
  mockSecureStoreValues.clear();
  mockSecureStoreSet.mockClear();
  mockSlot = "active";
  mockPlay = false;
  mockPlus = false;
  shell.server = "https://digitvav3.causeofdeathindia.com";
  shell.userId = "a";
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
  mockCheckForUpdate.mockClear();
  mockCheckServerCompatibility.mockClear();
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

it("manually checks compatibility against the selected server and displays a short build revision", async () => {
  const tree = await render();
  expect(out(tree)).toContain(en.serverCompatibilityUnknown);
  await pressLabel(tree, en.serverCompatibilityCheck);
  expect(mockCheckServerCompatibility).toHaveBeenCalledWith(shell.server);
  expect(out(tree)).toContain(en.serverCompatibilityCompatible);
  expect(out(tree)).toContain("Server build abcdef01");
});

it("does not apply a compatibility result after the selected server changes", async () => {
  let resolveCheck!: (result: { status: "compatible"; buildRevision: string }) => void;
  const pending = new Promise<{ status: "compatible"; buildRevision: string }>((resolve) => { resolveCheck = resolve; });
  mockCheckServerCompatibility.mockImplementationOnce(() => pending);
  const tree = await render();
  const button = tree.root.findAll((node) => node.props.accessibilityLabel === en.serverCompatibilityCheck)[0];
  await act(async () => { void button.props.onPress(); await Promise.resolve(); });
  expect(mockCheckServerCompatibility).toHaveBeenCalledWith("https://digitvav3.causeofdeathindia.com");
  shell.server = "https://demo.example.org";
  await act(async () => { tree.update(<ShellContext.Provider value={shell}><NativeSettings /></ShellContext.Provider>); });
  resolveCheck({ status: "compatible", buildRevision: "abcdef0123456789abcdef0123456789abcdef01" });
  await act(async () => { await pending; });
  expect(out(tree)).toContain(en.serverCompatibilityUnknown);
  expect(out(tree)).not.toContain("abcdef01");
});

it("clears a pending update check when the selected server changes", async () => {
  let resolveOldCheck!: (result: UpdateResult) => void;
  const pending = new Promise<UpdateResult>((resolve) => { resolveOldCheck = resolve; });
  mockCheckForUpdate.mockImplementationOnce(() => pending);
  mockCheckForUpdate.mockResolvedValueOnce({ status: "current" });
  const tree = await render();
  const button = tree.root.findAll((node) => node.props.accessibilityLabel === en.updateCheck)[0];
  await act(async () => { void button.props.onPress(); await Promise.resolve(); });
  expect(button.props.disabled).toBe(true);

  shell.server = "https://demo.example.org";
  await act(async () => { tree.update(<ShellContext.Provider value={shell}><NativeSettings /></ShellContext.Provider>); });
  const nextButton = tree.root.findAll((node) => node.props.accessibilityLabel === en.updateCheck)[0];
  expect(nextButton.props.disabled).toBe(false);
  await pressLabel(tree, en.updateCheck);
  expect(mockCheckForUpdate).toHaveBeenLastCalledWith("https://demo.example.org");
  expect(out(tree)).toContain(en.updateCurrent);

  resolveOldCheck({ status: "available", version: "stale", url: "https://example.org/old.apk" });
  await act(async () => { await pending; });
  expect(out(tree)).toContain(en.updateCurrent);
  expect(out(tree)).not.toContain("stale");
});

it("keeps the Active or demo switcher out of standalone Settings", async () => {
  const original = mockAccounts[0];
  mockAccounts[0] = { user_id: "offline", name: "EngineBenchmark", standalone: true };
  shell.userId = "offline";
  shell.server = undefined;
  try {
    expect(out(await render())).not.toContain("Active or demo");
  } finally {
    mockAccounts[0] = original;
    shell.userId = "a";
    shell.server = "https://digitvav3.causeofdeathindia.com";
  }
});

it("opens Profile and project access for the selected account", async () => {
  const tree = await render();
  await pressLabel(tree, en.profileAccessTitle);
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/profile-access", params: { userId: "a" } });
});

it("offers the offline engine check only to an eligible Plus account and passes its userId", async () => {
  mockPlus = true;
  mockAccounts[0].offline_coding_access = ["P"];
  try {
    const tree = await render();
    await pressLabel(tree, "Offline engine check");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/engine-check", params: { userId: "a" } });

    mockRouter.push.mockClear();
    mockAccounts[0].offline_coding_access = [];
    expect(out(await render())).not.toContain("Offline engine check");
    expect(mockRouter.push).not.toHaveBeenCalled();
  } finally {
    delete mockAccounts[0].offline_coding_access;
  }
});

it("hides the offline engine check in the plain build", async () => {
  mockAccounts[0].offline_coding_access = ["P"];
  try {
    expect(out(await render())).not.toContain("Offline engine check");
  } finally {
    delete mockAccounts[0].offline_coding_access;
  }
});

it("shows the device-wide ICD-11 / DORIS choice in Settings and saves changes without changing work", async () => {
  const tree = await render();
  const toggle = tree.root.findByProps({ accessibilityLabel: en.icd11DorisPreferenceTitle });
  expect(toggle.props.value).toBe(false);
  expect(mockSecureStoreSet).not.toHaveBeenCalled();
  const pushCount = mockRouter.push.mock.calls.length;
  await act(async () => { await toggle.props.onValueChange(true); });
  expect(mockSecureStoreSet).toHaveBeenCalledWith("digitva.icd11-doris-enabled.v1", "enabled");
  expect(tree.root.findByProps({ accessibilityLabel: en.icd11DorisPreferenceTitle }).props.value).toBe(true);
  expect(mockRouter.push).toHaveBeenCalledTimes(pushCount);
  expect(shell.sync.work?.unsent).toBe(2);
});

it("hides server sync controls for standalone and keeps its eligible engine check", async () => {
  mockPlus = true;
  mockAccounts[0].standalone = true;
  shell.server = undefined;
  mockAccounts[0].offline_coding_access = ["P"];
  try {
    const tree = await render();
    const text = out(tree);
    expect(text).not.toContain(`"${en.tabSync}"`);
    expect(text).not.toContain(`"${en.sendNow}"`);
    expect(text).toContain("Offline engine check");
    expect(shell.sendNow).not.toHaveBeenCalled();
  } finally {
    delete mockAccounts[0].standalone;
    delete mockAccounts[0].offline_coding_access;
  }
});

it.each(["standalone", "unrecognized account"])("ignores retained enrolment for %s while local settings and help remain available", async (context) => {
  shell.server = undefined;
  if (context === "standalone") mockAccounts[0].standalone = true;
  else shell.userId = undefined;
  const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
  try {
    const tree = await render();
    const text = out(tree);
    for (const label of [en.enrolledServer, en.deviceLabel, en.privacyPolicy, en.dataRequests, en.reEnrol, en.updateCheck, en.devicesTitle]) {
      expect(text).not.toContain(`"${label}"`);
    }
    expect(text).not.toContain("https://digitvav3.causeofdeathindia.com");
    expect(text).not.toContain("dev-1");
    expect(text).not.toContain(en.permissionsProjectCached.replace("{project}", "Project"));
    await pressLabel(tree, en.permissionsCheck);
    await pressLabel(tree, en.helpGuide);
    expect(mockReadDevicePermissions).toHaveBeenCalled();
    expect(shell.openSheet).toHaveBeenCalledWith("help");
    expect(mockRefreshAccessSummary).not.toHaveBeenCalled();
    expect(mockListMyDevices).not.toHaveBeenCalled();
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
    expect(mockCheckServerCompatibility).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  } finally {
    delete mockAccounts[0].standalone;
    open.mockRestore();
  }
});

it("standalone Play build keeps the explicit store listing without hosted update requests", async () => {
  mockPlay = true;
  shell.server = undefined;
  mockAccounts[0].standalone = true;
  const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
  try {
    const tree = await render();
    expect(open).not.toHaveBeenCalled();
    await pressLabel(tree, en.updateCheck);
    expect(open).toHaveBeenCalledWith("market://details?id=com.causeofdeathindia.digitvacollect");
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
    expect(mockCheckServerCompatibility).not.toHaveBeenCalled();
  } finally {
    delete mockAccounts[0].standalone;
    open.mockRestore();
  }
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

it("Google Play build: opens this package's Play listing and never checks hosted releases", async () => {
  mockPlay = true;
  const openURL = jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);
  try {
    const tree = await render();
    expect(out(tree)).toContain("App updates come from Google Play.");
    await pressLabel(tree, "Check for updates");
    expect(mockOpenURL).toHaveBeenCalledWith("market://details?id=com.causeofdeathindia.digitvacollect");
    expect(mockOpenURL).toHaveBeenCalledTimes(1);
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
  } finally {
    openURL.mockRestore();
  }
});

it("Google Play build falls back to the web listing for the configured Plus package", async () => {
  mockPlay = true;
  mockAndroidPackage = "com.causeofdeathindia.digitvacollect.plus";
  mockOpenURL.mockRejectedValueOnce(new Error("market handler unavailable"));
  const openURL = jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);
  try {
    const tree = await render();
    await pressLabel(tree, "Check for updates");
    expect(mockOpenURL.mock.calls).toEqual([
      ["market://details?id=com.causeofdeathindia.digitvacollect.plus"],
      ["https://play.google.com/store/apps/details?id=com.causeofdeathindia.digitvacollect.plus"],
    ]);
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
  } finally {
    openURL.mockRestore();
  }
});

it("Google Play build reports an error when package metadata is missing", async () => {
  mockPlay = true;
  mockAndroidPackage = undefined;
  const openURL = jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);
  try {
    const tree = await render();
    await pressLabel(tree, "Check for updates");
    expect(out(tree)).toContain("Something went wrong. Try again.");
    expect(mockOpenURL).not.toHaveBeenCalled();
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
  } finally {
    openURL.mockRestore();
  }
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
    shell.server = undefined;
    try {
      expect(out(await render())).not.toContain("Delete my account");
    } finally {
      delete mockAccounts[0].signed_out;
    }
  });
});
