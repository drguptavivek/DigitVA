/** Pins what Settings asks of the device list, the permissions check and the backup database, and in what order (digitva-r8nh.26). */
import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import type { UpdateResult } from "../src/updateCheck";

const mockRouter = { replace: jest.fn(), push: jest.fn(), back: jest.fn(), dismissTo: jest.fn(), dismissAll: jest.fn(), canDismiss: () => false };
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
let mockExtra: Record<string, unknown> | undefined;
jest.mock("expo-constants", () => ({ __esModule: true, default: { expoConfig: { android: { get package() { return mockAndroidPackage; } }, get extra() { return mockExtra; } } } }));
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
  biometricKind: async () => "fingerprint",
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
let mockUnlocked = true;
const mockOpenDb = jest.fn(async (_userId: string) => ({}));
jest.mock("../src/interviewerDb", () => ({ ...jest.requireActual("../src/interviewerDb"), isUnlocked: () => mockUnlocked, openInterviewerDb: (userId: string) => mockOpenDb(userId) }));
// A marker for the export, backup and restore panel; exportAllowed shows which variant a section renders.
jest.mock("../src/standalone/DataActions", () => ({
  DataActions: ({ exportAllowed = true }: { exportAllowed?: boolean }) => require("react").createElement("data-actions", { exportAllowed }),
}));
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

import { Alert, Linking, Platform, Text } from "react-native";

import { ApiError } from "../src/api";
import en from "../src/strings/en.json";
import themeEn from "../src/strings/theme-en.json";
import NativeSettings from "../src/nativeRoutes/settings";
import { ListRow, SegmentedControl, Separator, TextLink } from "../src/ui";
import { ShellContext, syncedText, type Shell } from "../src/nativeShell/shellContext";

const shell: Shell = {
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "a", server: "https://digitvav3.causeofdeathindia.com",
  sync: { work: { unsent: 2, attention: 0, inProgress: 1, items: [] }, lastAt: new Date(2026, 9, 23, 9, 7).getTime(), busy: false, result: undefined, offline: false },
  sendNow: jest.fn(async () => undefined), recount: jest.fn(async () => undefined), refreshNow: jest.fn(async () => undefined), header: true, tabs: true,
  titleInBar: true, screenTitle: undefined, publishTitle: jest.fn(),
};

async function render(): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<ShellContext.Provider value={shell}><NativeSettings /></ShellContext.Provider>); });
  return tree;
}
/** A row's spoken name is its label, then its second line and value ("Check for updates, App updates come from..."). */
const named = (n: ReactTestInstance, label: string) => n.props.accessibilityLabel === label || String(n.props.accessibilityLabel ?? "").startsWith(`${label}, `);
const pressLabel = async (tree: ReactTestRenderer, label: string) => {
  const target = tree.root.findAll((n) => named(n, label) && typeof n.props.onPress === "function")[0];
  expect(target).toBeDefined();
  await act(async () => { await target.props.onPress(); });
};
const out = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());
/** Settings toggles are Switches: flip the one named `label`. */
const toggle = async (tree: ReactTestRenderer, label: string, on: boolean) => {
  const target = tree.root.findAll((n) => n.props.accessibilityLabel === label && n.props.accessibilityRole === "switch" && typeof n.props.onValueChange === "function")[0];
  expect(target).toBeDefined();
  await act(async () => { await target.props.onValueChange(on); });
};

beforeEach(() => {
  jest.clearAllMocks();
  // The update row is Android-only; jest-expo defaults to iOS.
  Platform.OS = "android";
  mockExtra = undefined;
  mockBiometricAvailable = true;
  mockAndroidPackage = "com.causeofdeathindia.digitvacollect";
  mockScreenLockOn = false;
  mockScreenLockPossible = true;
  mockSecureStoreValues.clear();
  mockSecureStoreSet.mockClear();
  mockSlot = "active";
  mockPlay = false;
  mockPlus = false;
  mockUnlocked = true;
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


const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

it("asks for the device list, then the phone permissions, once each on mount", async () => {
  await render();
  expect(mockListMyDevices).toHaveBeenCalledTimes(1);
  expect(mockListMyDevices).toHaveBeenCalledWith("a");
  expect(mockReadDevicePermissions).toHaveBeenCalledTimes(1);
  expect(mockListMyDevices.mock.invocationCallOrder[0]).toBeLessThan(mockReadDevicePermissions.mock.invocationCallOrder[0]);
  expect(mockRefreshAccessSummary).not.toHaveBeenCalled();
});

it("does not list devices without an enrolled server", async () => {
  shell.server = undefined as unknown as string;
  await render();
  expect(mockListMyDevices).not.toHaveBeenCalled();
  expect(mockReadDevicePermissions).toHaveBeenCalledTimes(1);
});

it("the permissions check reads the phone first, then project access, then reloads", async () => {
  const tree = await render();
  mockReadDevicePermissions.mockClear();
  await pressLabel(tree, en.permissionsCheck);
  expect(mockReadDevicePermissions).toHaveBeenCalledTimes(1);
  expect(mockReadDevicePermissions.mock.invocationCallOrder[0]).toBeLessThan(mockRefreshAccessSummary.mock.invocationCallOrder[0]);
  expect(mockRefreshAccessSummary.mock.invocationCallOrder[0]).toBeLessThan(mockReload.mock.invocationCallOrder[0]);
});

it("the permissions check says it is offline, and asks the server for nothing, while the phone is offline", async () => {
  shell.sync.offline = true;
  try {
    const tree = await render();
    await pressLabel(tree, en.permissionsCheck);
    expect(mockRefreshAccessSummary).not.toHaveBeenCalled();
    expect(mockReload).not.toHaveBeenCalled();
    expect(out(tree)).toContain(en.permissionsOffline);
  } finally {
    shell.sync.offline = false;
  }
});

it("the permissions check says it is offline when the server returns no summary, and does not reload", async () => {
  mockRefreshAccessSummary.mockResolvedValueOnce(undefined as never);
  const tree = await render();
  await pressLabel(tree, en.permissionsCheck);
  expect(mockRefreshAccessSummary).toHaveBeenCalledWith("a");
  expect(mockReload).not.toHaveBeenCalled();
  expect(out(tree)).toContain(en.permissionsOffline);
});

it("enabling one permission keeps the other as last read", async () => {
  mockReadDevicePermissions.mockResolvedValueOnce({ camera: { granted: false, canAskAgain: true }, microphone: { granted: true, canAskAgain: true } });
  const tree = await render();
  await pressLabel(tree, themeEn.permissionsCameraLabel);
  expect(tree.root.findByProps({ testID: "permission-camera" }).props.onPress).toBeUndefined();
  expect(tree.root.findByProps({ testID: "permission-microphone" }).props.onPress).toBeUndefined();
});

it("a changed server clears the project access shown by the last check", async () => {
  const tree = await render();
  const collection = () => tree.root.findAllByType(ListRow).find((n) => n.props.label === themeEn.permissionsCollectionLabel)?.props.value;
  expect(collection()).toBe(en.permissionsStatusUnknown);
  await pressLabel(tree, en.permissionsCheck);
  expect(collection()).toBe(en.permissionsStatusAllowed);
  await act(async () => { tree.update(<ShellContext.Provider value={{ ...shell, server: "https://other.example.org" }}><NativeSettings /></ShellContext.Provider>); });
  await flush();
  expect(collection()).toBe(en.permissionsStatusUnknown);
});

it("a device-list failure shows its error and a retry asks again", async () => {
  mockListMyDevices.mockRejectedValueOnce(new Error("network"));
  const tree = await render();
  expect(mockListMyDevices).toHaveBeenCalledTimes(1);
  await pressLabel(tree, en.devicesRetry);
  expect(mockListMyDevices).toHaveBeenCalledTimes(2);
  expect(mockListMyDevices).toHaveBeenLastCalledWith("a");
});

describe("backup database", () => {
  it("opens for an unlocked enrolled Plus account and shows the backup panel", async () => {
    mockPlus = true;
    const tree = await render();
    await flush();
    expect(mockOpenDb).toHaveBeenCalledTimes(1);
    expect(mockOpenDb).toHaveBeenCalledWith("a");
    expect(tree.root.findAll((n) => (n.type as unknown) === "data-actions")).toHaveLength(1);
  });

  it("stays closed for the plain build", async () => {
    const tree = await render();
    await flush();
    expect(mockOpenDb).not.toHaveBeenCalled();
    expect(tree.root.findAll((n) => (n.type as unknown) === "data-actions")).toHaveLength(0);
  });

  it("stays closed while the account is locked", async () => {
    mockPlus = true;
    mockUnlocked = false;
    const tree = await render();
    await flush();
    expect(mockOpenDb).not.toHaveBeenCalled();
    expect(tree.root.findAll((n) => (n.type as unknown) === "data-actions")).toHaveLength(0);
  });
});
