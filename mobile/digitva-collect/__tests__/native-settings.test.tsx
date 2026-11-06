/** Native Settings: its sections, the enrolled server (read-only, changed only by re-enrolling), and the actions each section keeps. */
import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
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
jest.mock("../src/interviewerDb", () => ({ ...jest.requireActual("../src/interviewerDb"), isUnlocked: () => mockUnlocked, openInterviewerDb: async () => ({}) }));
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

it("is titled Settings in the phone bar and shows every section", async () => {
  const tree = await render();
  const text = out(tree);
  // A pushed screen: the title goes to the bar next to the back arrow, not onto the page.
  expect(shell.publishTitle).toHaveBeenCalledWith(expect.any(Object), "Settings");
  const onPage = tree.root.findAll((n) => n.props.accessibilityRole === "header" && typeof n.props.children === "string").map((n) => n.props.children);
  expect(onPage).toContain("Account");
  expect(onPage).not.toContain("Settings");
  for (const heading of ["Account", "Devices", "Phone", "Display", "Security", "Diagnostics", "Help & support", "About"]) expect(onPage).toContain(heading);
  // Sync lives on the Sync tab and sheet: Settings has no Sync section, no sync time and no Send now.
  expect(onPage).not.toContain("Sync");
  expect(text).not.toContain(syncedText(shell.sync.lastAt));
  expect(text).not.toContain("2 unsent");
  expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Send now")).toHaveLength(0);
  expect(text).toContain('"digitvav3.causeofdeathindia.com"'); // the host, in the mono value column
  expect(text).toContain("dev-1");
  // Auto-lock is a value row of Account, not a sentence glued onto a footer.
  const autoLock = tree.root.findByProps({ testID: "auto-lock" });
  expect(autoLock.props.label).toBe(themeEn.settingsAutoLock);
  expect(autoLock.props.value).toBe("5 minutes");
  expect(text).not.toContain("The app locks after");
  const version = tree.root.findAllByType(ListRow).find((n) => n.props.label === themeEn.appVersionRowLabel);
  expect(version).toBeDefined();
  expect(String(version!.props.value)).toMatch(/^\d+\.\d+\.\d+/);
});

it("draws Mode and App language as labelled rows with 36pt segmented controls, like Text size", async () => {
  const tree = await render();
  for (const label of ["Mode", en.appLanguage, "Text size"]) {
    const control = tree.root.findAllByType(SegmentedControl).find((n) => n.props.accessibilityLabel === label);
    expect(control).toBeDefined();
    expect(control!.props.compact).toBe(true);
    // The nearest ancestor holding other text is the row, and its first text is the row's label.
    let row = control!.parent!;
    while (row.findAllByType(Text).length === control!.findAllByType(Text).length) row = row.parent!;
    expect(row.findAllByType(Text)[0].props.children).toBe(label);
  }
  const compact = tree.root.findAllByType(SegmentedControl).filter((n) => n.props.compact === true).map((n) => n.props.accessibilityLabel);
  expect(compact).toEqual(expect.arrayContaining(["Mode", en.appLanguage, "Text size"]));
});

it("draws every switch in the theme: primary track on, border track off, white thumb", async () => {
  const { getTheme, SWITCH_THUMB } = jest.requireActual("../src/theme") as typeof import("../src/theme");
  const t = getTheme("light").ui;
  const tree = await render();
  const switches = tree.root.findAll((n) => typeof n.props.onValueChange === "function" && n.props.trackColor !== undefined);
  expect(switches.length).toBeGreaterThanOrEqual(3);
  for (const node of switches) {
    expect(node.props.trackColor).toEqual({ false: t.border, true: t.primary });
    expect(node.props.thumbColor).toBe(SWITCH_THUMB);
    expect(node.props.ios_backgroundColor).toBe(t.border);
  }
  expect(SWITCH_THUMB.toLowerCase()).toBe("#ffffff");
});

it("puts Export errors first as an action row and the Usage diagnostics switch last, under which the footer explains it", async () => {
  const tree = await render();
  const exportRow = tree.root.findAll((n) => n.props.label === en.exportErrors && n.props.action === true);
  expect(exportRow).toHaveLength(1);
  const text = out(tree);
  expect(text.indexOf(en.exportErrors)).toBeLessThan(text.indexOf(en.telemetryTitle));
  expect(text.indexOf(en.telemetryTitle)).toBeLessThan(text.indexOf(en.telemetryDescription.slice(0, 20)));
});

it("keeps the backup rows, drops the coded-case rows from Collect Plus, and no row there has a glyph", async () => {
  mockPlus = true;
  const original = mockAccounts[0];
  mockAccounts[0] = { ...original, offline_coding_access: ["P"] };
  try {
    const tree = await render();
    const onPage = tree.root.findAll((n) => n.props.accessibilityRole === "header" && typeof n.props.children === "string").map((n) => n.props.children);
    expect(onPage).toContain(en.collectPlusSection);
    expect(onPage).toContain(en.settingsBackup);
    for (const gone of [en.localCases, en.onlineCases, en.myCodedCases]) expect(out(tree)).not.toContain(gone);
    const plusRows = tree.root.findAll((n) => (n.props.label === en.offlineEngineCheck || n.props.label === en.offlineProfileTitle) && n.props.onPress);
    expect(plusRows.length).toBeGreaterThanOrEqual(1);
    expect(plusRows.every((row) => row.props.icon === undefined)).toBe(true);
  } finally {
    mockAccounts[0] = original;
  }
});

it("manually checks compatibility against the selected server and displays a short build revision", async () => {
  const tree = await render();
  // An action row: primary label, no status line until a check has run.
  const row = () => tree.root.findAll((n) => n.props.label === en.serverCompatibilityCheck && n.props.action === true)[0];
  expect(row()).toBeDefined();
  expect(row().props.secondary).toBeUndefined();
  await pressLabel(tree, en.serverCompatibilityCheck);
  expect(mockCheckServerCompatibility).toHaveBeenCalledWith(shell.server);
  expect(row().props.secondary).toBe("Compatible with server abcdef01");
  expect(row().props.secondaryTone).toBeUndefined();
  expect(out(tree)).not.toContain(en.serverCompatibilityLabel);
});

it("says once, in the error colour, when the server could not be reached", async () => {
  mockCheckServerCompatibility.mockResolvedValueOnce({ status: "unknown" } as never);
  const tree = await render();
  await pressLabel(tree, en.serverCompatibilityCheck);
  const row = tree.root.findAll((n) => n.props.label === en.serverCompatibilityCheck && n.props.action === true)[0];
  expect(row.props.secondary).toBe(themeEn.serverUnreachable);
  expect(row.props.secondaryTone).toBe("destructive");
});

it("does not apply a compatibility result after the selected server changes", async () => {
  let resolveCheck!: (result: { status: "compatible"; buildRevision: string }) => void;
  const pending = new Promise<{ status: "compatible"; buildRevision: string }>((resolve) => { resolveCheck = resolve; });
  mockCheckServerCompatibility.mockImplementationOnce(() => pending);
  const tree = await render();
  const button = tree.root.findAll((node) => named(node, en.serverCompatibilityCheck) && typeof node.props.onPress === "function")[0];
  await act(async () => { void button.props.onPress(); await Promise.resolve(); });
  expect(mockCheckServerCompatibility).toHaveBeenCalledWith("https://digitvav3.causeofdeathindia.com");
  shell.server = "https://demo.example.org";
  await act(async () => { tree.update(<ShellContext.Provider value={shell}><NativeSettings /></ShellContext.Provider>); });
  resolveCheck({ status: "compatible", buildRevision: "abcdef0123456789abcdef0123456789abcdef01" });
  await act(async () => { await pending; });
  expect(out(tree)).toContain(en.serverCompatibilityCheck);
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
    const tree = await render();
    expect(tree.root.findAll((n) => n.props.accessibilityRole === "header" && n.props.children === en.settingsSlot)).toHaveLength(0);
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Demo" && n.props.accessibilityRole === "radio")).toHaveLength(0);
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
  const coding = () => tree.root.findByProps({ accessibilityLabel: themeEn.codingOnPhone, accessibilityRole: "switch" });
  expect(coding().props.value).toBe(true); // plain Collect defaults on
  expect(mockSecureStoreSet).not.toHaveBeenCalled();
  const pushCount = mockRouter.push.mock.calls.length;
  await toggle(tree, themeEn.codingOnPhone, false);
  expect(mockSecureStoreSet).toHaveBeenCalledWith("digitva.icd11-doris-enabled.v1", "disabled");
  expect(coding().props.value).toBe(false);
  expect(mockRouter.push).toHaveBeenCalledTimes(pushCount);
  expect(shell.sync.work?.unsent).toBe(2);
});

it.each([[false, "icd11DorisPreferenceScopeOnline", "offline"], [true, "icd11DorisPreferenceScope", "needs a connection"]] as const)(
  "describes ICD-11 / DORIS coding by what the build carries (Plus %s)", async (plus, shown, absent) => {
    mockPlus = plus;
    const text = out(await render());
    expect(text).toContain(en[shown]);
    expect(text).not.toContain(absent);
    expect(text).not.toContain(en.icd11DorisPreferenceChangeLater);
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
    for (const label of [en.enrolledServer, en.deviceLabel, themeEn.deviceIdLabel, themeEn.settingsSectionDevices, en.privacyPolicy, en.dataRequests, en.reEnrol, en.updateCheck, en.devicesTitle]) {
      expect(text).not.toContain(`"${label}"`);
    }
    expect(text).not.toContain("https://digitvav3.causeofdeathindia.com");
    expect(text).not.toContain("dev-1");
    expect(text).not.toContain(en.permissionsProjectCached.replace("{project}", "Project"));
    expect(text).not.toContain(`"${en.permissionsCheck}"`);
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

it("keeps the app language choice and fingerprint enabling, with no back-only Home button (the header arrow goes back)", async () => {
  const tree = await render();
  await pressLabel(tree, "हिन्दी");
  expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  await toggle(tree, "Use fingerprint", true);
  expect(mockLockNow).toHaveBeenCalled();
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "a", enableBiometric: "1" } });
  expect(out(tree)).toContain(en.updateCheck);
  expect(tree.root.findAll((node) => node.props.label === en.home)).toHaveLength(0);
});

it("offers no fingerprint button on a phone without biometrics", async () => {
  mockBiometricAvailable = false;
  expect(out(await render())).not.toContain("Use fingerprint");
});

it("opens Help from Help & support", async () => {
  const tree = await render();
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
  // The Camera row itself is the action (no separate Allow link); its spoken name says what a press does.
  const camera = tree.root.findByProps({ testID: "permission-camera" });
  expect(camera.props.accessibilityLabel).toBe(`${themeEn.permissionsCameraLabel}, ${en.permissionsStatusNotGranted}. ${en.permissionsEnableCamera}`);
  expect(out(tree)).not.toContain('"Allow"');
  await pressLabel(tree, themeEn.permissionsCameraLabel);
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
    // An allowed row is a plain value row (no press); the blocked one opens the phone's settings.
    expect(tree.root.findByProps({ testID: "permission-microphone" }).props.onPress).toBeUndefined();
    expect(tree.root.findByProps({ testID: "permission-camera" }).props.accessibilityLabel).toContain(en.permissionsOpenSettings);
    await pressLabel(tree, themeEn.permissionsCameraLabel);
    expect(openSettings).toHaveBeenCalled();
    expect(mockRequestDevicePermission).not.toHaveBeenCalled();
  } finally {
    openSettings.mockRestore();
  }
});

it("shows project access and its check only after the PIN unlocks the account", async () => {
  mockUnlocked = false;
  const text = out(await render());
  expect(text).toContain(`"${themeEn.permissionsCameraLabel}"`);
  for (const hidden of [en.permissionsCheck, en.permissionsHint]) expect(text).not.toContain(hidden);
  expect(text).not.toContain(themeEn.permissionsCollectionLabel);
  expect(text).not.toContain(themeEn.permissionsCodingLabel);
  expect(mockRefreshAccessSummary).not.toHaveBeenCalled();
});

it("offers Profile and project access only after the PIN unlocks the account", async () => {
  const labelled = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function");
  const unlockedTree = await render();
  expect(labelled(unlockedTree, en.profileAccessTitle)).toHaveLength(1);
  mockUnlocked = false;
  const lockedTree = await render();
  expect(labelled(lockedTree, en.profileAccessTitle)).toHaveLength(0);
});

it("standalone shows no project access lines or refresh check, keeps device permissions, and uses the standalone ICD-11 scope", async () => {
  const original = mockAccounts[0];
  mockAccounts[0] = { user_id: "a", name: "Asha", standalone: true };
  shell.server = undefined;
  mockPlus = true;
  try {
    const tree = await render();
    const text = out(tree);
    expect(text).toContain(`"${themeEn.permissionsCameraLabel}"`);
    expect(text).toContain(en.icd11DorisPreferenceScopeStandalone);
    expect(text).not.toContain(en.icd11DorisPreferenceScope);
    expect(text).not.toContain(en.permissionsHint);
    expect(text).not.toContain(themeEn.permissionsCollectionLabel);
    expect(text).not.toContain(themeEn.permissionsCodingLabel);
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === en.permissionsCheck)).toHaveLength(0);
  } finally {
    mockAccounts[0] = original;
    shell.server = "https://digitvav3.causeofdeathindia.com";
  }
});

it("gives an unlocked standalone account Enrol this phone and Export and backup, and an enrolled one only the unsent-work backup", async () => {
  const original = mockAccounts[0];
  mockPlus = true;
  const labelled = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function");
  const panels = (tree: ReactTestRenderer) => tree.root.findAllByType("data-actions" as never);
  try {
    mockAccounts[0] = { user_id: "a", name: "Asha", standalone: true };
    shell.server = undefined;
    const tree = await render();
    expect(out(tree)).toContain(en.standaloneDataSection);
    expect(panels(tree)).toHaveLength(1);
    expect(panels(tree)[0].props.exportAllowed).toBe(true);
    expect(out(tree)).not.toContain(en.settingsBackup);
    await pressLabel(tree, en.standaloneEnrol);
    expect(mockRouter.push).toHaveBeenCalledWith("/enrol");

    mockUnlocked = false;
    const locked = await render();
    expect(labelled(locked, en.standaloneEnrol)).toHaveLength(1);
    expect(panels(locked)).toHaveLength(0);

    mockUnlocked = true;
    mockAccounts[0] = { user_id: "a", name: "Asha" };
    shell.server = "https://digitvav3.causeofdeathindia.com";
    const enrolled = await render();
    expect(out(enrolled)).toContain(en.settingsBackup);
    expect(panels(enrolled)).toHaveLength(1);
    expect(panels(enrolled)[0].props.exportAllowed).toBe(false);
    expect(labelled(enrolled, en.standaloneEnrol)).toHaveLength(0);
    expect(out(enrolled)).not.toContain(en.standaloneDataSection);
  } finally {
    mockAccounts[0] = original;
    shell.server = "https://digitvav3.causeofdeathindia.com";
  }
});

it("refreshes cached project access through the explicit permissions check", async () => {
  const tree = await render();
  await pressLabel(tree, en.permissionsCheck);
  expect(mockRefreshAccessSummary).toHaveBeenCalledWith("a");
  expect(mockReload).toHaveBeenCalled();
  expect(out(tree)).toContain(themeEn.permissionsFooter.replace("{project}", "Project"));
  expect(out(tree)).toContain(themeEn.permissionsCollectionLabel);
});

it("lists devices and removes another phone by refreshing only the device list", async () => {
  const alertSpy = jest.spyOn(Alert, "alert").mockImplementation(() => undefined);
  mockListMyDevices.mockResolvedValueOnce(mockDevices).mockResolvedValueOnce([mockDevices[0]]);
  try {
    const tree = await render();
    const removeButtons = tree.root.findAllByType(TextLink).filter((node) => String(node.props.accessibilityLabel).startsWith(`${en.deviceDecommission}: `));
    // Another phone: a red Remove. This phone: a primary Sign out (its data stays), titled "This phone".
    expect(removeButtons).toHaveLength(1);
    expect(removeButtons[0].props.tone).toBe("destructive");
    const signOut = tree.root.findAllByType(TextLink).filter((node) => node.props.label === themeEn.deviceRemoveCurrent);
    expect(signOut).toHaveLength(1);
    expect(signOut[0].props.tone).toBeUndefined();
    expect(tree.root.findByProps({ testID: `device-${mockDevices[0].device_id}` }).props.label).toBe(en.deviceCurrent);
    expect(out(tree)).toContain(en.devicesCount.replace("{count}", "2"));
    await act(async () => { removeButtons[0].props.onPress(); });
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
    const remove = tree.root.findAll((node) => node.props.accessibilityLabel === `${themeEn.deviceRemoveCurrent}: ${en.deviceCurrent}` && typeof node.props.onPress === "function")[0];
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
  await toggle(tree, "Use phone screen lock", true);
  expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/unlock", params: { userId: "a", enableScreenLock: "1" } });
  mockScreenLockOn = true;
  const on = await render();
  expect(on.root.findByProps({ accessibilityLabel: "Use phone screen lock", accessibilityRole: "switch" }).props.value).toBe(true);
  await toggle(on, "Use phone screen lock", false);
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
  // The slot is a segmented control: the slot in use is the checked segment.
  const checked = (label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && n.props.accessibilityRole === "radio")[0]?.props.accessibilityState.checked;
  expect(checked("Active")).toBe(true);
  expect(checked("Demo")).toBe(false);
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

it("shows no update row on iOS without an App Store id", async () => {
  Platform.OS = "ios";
  const tree = await render();
  expect(out(tree)).toContain(themeEn.settingsSectionDevices);
  expect(tree.root.findAll((node) => node.props.accessibilityLabel === en.updateCheck)).toHaveLength(0);
  expect(out(tree)).not.toContain("App updates come from");
  expect(mockCheckForUpdate).not.toHaveBeenCalled();
});

it("iOS build: opens the App Store listing when its id is configured and never checks hosted releases", async () => {
  Platform.OS = "ios";
  mockExtra = { digitvaIosAppStoreId: "1234567890" };
  const openURL = jest.spyOn(Linking, "openURL").mockImplementation(mockOpenURL);
  try {
    const tree = await render();
    expect(out(tree)).toContain(en.updateAppStore);
    expect(out(tree)).not.toContain(en.updatePlayStore);
    await pressLabel(tree, en.updateCheck);
    expect(mockOpenURL.mock.calls).toEqual([["itms-apps://apps.apple.com/app/id1234567890"]]);
    expect(mockCheckForUpdate).not.toHaveBeenCalled();
  } finally {
    openURL.mockRestore();
  }
});

describe("round-3 Settings layout", () => {
  const cardLabelled = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.label === label && n.props.grouped === true && "footer" in n.props)[0];
  const row = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.label === label && "action" in n.props)[0];

  it("puts Mode and App language in one PHONE card with one footer", async () => {
    const tree = await render();
    const phone = cardLabelled(tree, themeEn.settingsPhone);
    expect(phone).toBeDefined();
    expect(phone.props.footer).toBe(themeEn.settingsPhoneNote);
    const controls = phone.findAllByType(SegmentedControl).map((n) => n.props.accessibilityLabel);
    expect(controls).toEqual(["Mode", en.appLanguage]);
    const headers = tree.root.findAll((n) => n.props.accessibilityRole === "header" && typeof n.props.children === "string").map((n) => n.props.children);
    expect(headers).toContain(themeEn.settingsPhone);
    expect(headers).not.toContain(en.settingsLanguage);
    expect(headers).not.toContain(en.settingsSlot);
    // App language takes the same control width as Mode and Text size, so the card's controls line up.
    const { StyleSheet } = jest.requireActual("react-native") as typeof import("react-native");
    expect(StyleSheet.flatten(tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "language-control")[0].props.style)).toMatchObject({ flex: 1, maxWidth: 240 });
  });

  it("separates the empty devices row from Refresh devices with a hairline", async () => {
    mockListMyDevices.mockResolvedValueOnce([]);
    const tree = await render();
    const devices = cardLabelled(tree, themeEn.settingsSectionDevices);
    const children = devices.findAll((n) => n.type === Separator || n.type === ListRow);
    const labels = children.map((n) => (n.type === Separator ? "|" : n.props.label));
    expect(labels).toEqual([en.devicesNone, "|", en.devicesRefresh]);
  });

  it("draws Refresh devices and Refresh access as the last action rows of their cards, not loose links", async () => {
    const tree = await render();
    const devices = cardLabelled(tree, themeEn.settingsSectionDevices);
    const refreshDevices = row(tree, en.devicesRefresh);
    expect(refreshDevices.props.action).toBe(true);
    expect(devices.findAll((n) => n === refreshDevices)).toHaveLength(1);
    const permissions = cardLabelled(tree, themeEn.settingsSectionPermissions);
    const refreshAccess = row(tree, themeEn.permissionsRefreshNow);
    expect(themeEn.permissionsRefreshNow).toBe("Refresh access");
    expect(refreshAccess.props.action).toBe(true);
    expect(permissions.findAll((n) => n === refreshAccess)).toHaveLength(1);
    // Every permissions row keeps the chevron slot, so the four values share one right edge.
    expect(permissions.props.chevronSlot).toBe(true);
    expect(tree.root.findAllByType(TextLink).map((n) => n.props.label)).not.toEqual(expect.arrayContaining([en.devicesRefresh, themeEn.permissionsRefreshNow]));
  });

  it("gives the ACCOUNT name row the account's phone roles as its value", async () => {
    const original = mockAccounts[0];
    mockAccounts[0] = { ...original, collection_access: true, registration_access: true } as typeof original;
    try {
      const tree = await render();
      const nameRow = tree.root.findAll((n) => n.props.label === "Asha" && "value" in n.props)[0];
      expect(nameRow.props.value).toBe(`${en.role_interviewer} · ${en.role_death_reporter}`);
    } finally {
      mockAccounts[0] = original;
    }
    // No phone roles: the bare name, no empty value.
    const tree = await render();
    expect(tree.root.findAll((n) => n.props.label === "Asha" && "value" in n.props)[0].props.value).toBeUndefined();
  });
});
