/** ShellProvider: the interviewer a screen belongs to, the sync status, Send now / Refresh from any screen, and the error-log route. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockPathname = "/worklist";
let mockParams: Record<string, string> = { userId: "u1" };
let mockUnsent = 2;
let mockLastFull: number | null = null;
const mockDataChanged = jest.fn();
const mockReload = jest.fn(async () => undefined);
const mockSync = jest.fn(async (..._args: unknown[]) => ({ sync: { sent: 2, failed: 0, remaining: 0 }, reference: undefined }));
const mockToast = jest.fn();
const mockRefreshReference = jest.fn(async (..._args: unknown[]) => ({ projects: [] }));
const mockRefreshDefs = jest.fn(async (..._args: unknown[]) => undefined);
const mockRefreshCases = jest.fn(async (..._args: unknown[]) => undefined);
const mockSetRoute = jest.fn();
let mockAccounts: Array<{ user_id: string; name: string; server?: string; standalone?: boolean; signed_out?: boolean }>;

jest.mock("expo-router", () => ({ usePathname: () => mockPathname, useGlobalSearchParams: () => mockParams, useRouter: () => ({}) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ accounts: mockAccounts, lockVersion: 0, offline: false, dataChanged: mockDataChanged, syncAccount: mockSync, reload: mockReload, device: mockDevice }),
}));
let mockDevice: { server: string } | undefined;
let mockPlay = false;
jest.mock("../src/appVariant", () => ({ isPlayDistribution: () => mockPlay }));
const mockDailyCheck = jest.fn(async (_server?: string) => ({ status: "available", version: "9.9.9", url: "https://example.org/digitva.apk" }));
jest.mock("../src/updateCheck", () => ({ checkForUpdateDaily: (server?: string) => mockDailyCheck(server) }));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => true,
  openInterviewerDb: async () => ({ db: true }),
  unsentWork: async () => ({ unsent: mockUnsent, attention: 0, inProgress: 0, items: [] }),
}));
jest.mock("../src/notificationState", () => ({ readNotificationState: async () => ({ lastSuccessfulFullSyncAt: mockLastFull }) }));
jest.mock("../src/sync", () => ({
  refreshReferenceData: (...args: unknown[]) => mockRefreshReference(...args),
  refreshAuthorizedProjectDefinitions: (...args: unknown[]) => mockRefreshDefs(...args),
  refreshCases: (...args: unknown[]) => mockRefreshCases(...args),
}));
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));
jest.mock("../src/errorLogDb", () => ({ installErrorLog: () => () => undefined }));
jest.mock("../src/errorLog", () => ({ flushErrors: jest.fn(), setErrorRoute: (path: string) => mockSetRoute(path), recordError: jest.fn(), describeError: () => "x" }));
jest.mock("../src/nativeShell/sheets", () => ({ AccountSheet: () => null, HelpSheet: () => null, SyncSheet: () => null }));
jest.mock("../src/ui", () => ({ errorText: (e: unknown) => `err:${String(e)}\nRef: x` }));

let mockOffline = false;
jest.mock("../src/network", () => ({ ...jest.requireActual("../src/network"), isOffline: () => mockOffline }));

import { ShellProvider } from "../src/nativeShell/shell";
import { useShell, type Shell } from "../src/nativeShell/shellContext";

let shell!: Shell;
function Probe() {
  shell = useShell();
  return null;
}
let tree: ReactTestRenderer;
const mount = async () => { await act(async () => { tree = create(<ShellProvider><Probe /></ShellProvider>); }); };

beforeEach(() => {
  jest.clearAllMocks();
  mockPathname = "/worklist";
  mockParams = { userId: "u1" };
  mockUnsent = 2;
  mockLastFull = null;
  mockOffline = false;
  mockDevice = undefined;
  mockPlay = false;
  mockAccounts = [{ user_id: "u1", name: "Asha", server: "https://digitvav3.causeofdeathindia.com" }];
});
afterEach(async () => { await act(async () => tree.unmount()); });

it("sideloaded build: the start-up update check offers the hosted APK download", async () => {
  mockDevice = { server: "https://digitvav3.causeofdeathindia.com" };
  await mount();
  expect(mockDailyCheck).toHaveBeenCalledWith("https://digitvav3.causeofdeathindia.com");
  expect(mockToast).toHaveBeenCalledWith(expect.objectContaining({ text: "Update available: 9.9.9", action: expect.objectContaining({ label: "Download" }) }));
});

it("Google Play build: no start-up update check and no Download toast", async () => {
  mockDevice = { server: "https://digitvav3.causeofdeathindia.com" };
  mockPlay = true;
  await mount();
  expect(mockDailyCheck).not.toHaveBeenCalled();
  expect(mockToast).not.toHaveBeenCalled();
});

it.each(["https://active.example.org", "https://demo.example.org"])("exposes only the selected server account's matching enrolment: %s", async (server) => {
  mockAccounts[0].server = server;
  mockDevice = { server };
  await mount();
  expect(shell.server).toBe(server);
  expect(mockDailyCheck).toHaveBeenCalledWith(server);
});

it.each(["standalone", "signed out", "unknown account", "no account", "missing server", "different server", "unknown server"])("does not check updates or expose a retained device server for %s", async (context) => {
  mockDevice = { server: "https://digitvav3.causeofdeathindia.com" };
  if (context === "standalone") mockAccounts[0].standalone = true;
  if (context === "signed out") mockAccounts[0].signed_out = true;
  if (context === "unknown account") mockParams = { userId: "stranger" };
  if (context === "no account") mockParams = {};
  if (context === "missing server") delete mockAccounts[0].server;
  if (context === "different server") mockAccounts[0].server = "https://other.example.org";
  if (context === "unknown server") {
    mockAccounts[0].server = "unknown";
    mockDevice.server = "unknown";
  }
  await mount();
  expect(shell.server).toBeUndefined();
  expect(mockDailyCheck).not.toHaveBeenCalled();
  expect(mockToast).not.toHaveBeenCalled();
});

it("resolves the interviewer from the route, counts unsent work and files the screen for the error log", async () => {
  mockLastFull = new Date(2026, 9, 23, 8, 30).getTime();
  await mount();
  expect(shell.userId).toBe("u1");
  expect(shell.sync.work?.unsent).toBe(2);
  expect(shell.sync.lastAt).toBe(mockLastFull);
  expect(shell.header).toBe(true);
  expect(shell.tabs).toBe(true);
  expect(mockSetRoute).toHaveBeenCalledWith("/worklist");
});

it("ignores a userId that is not an account on this phone", async () => {
  mockParams = { userId: "stranger" };
  await mount();
  expect(shell.userId).toBeUndefined();
  expect(shell.tabs).toBe(false);
});

it("shows no tabs on a form and no header either", async () => {
  mockPathname = "/form";
  await mount();
  expect(shell.header).toBe(false);
  expect(shell.tabs).toBe(false);
});

it("Send now syncs, records the result line, updates the time and tells mounted lists to reload", async () => {
  await mount();
  await act(async () => { await shell.sendNow(); });
  expect(mockSync).toHaveBeenCalledWith("u1", { db: true });
  expect(shell.sync.result).toBe("Sent 2. Not accepted 0. Still on this phone 0.");
  expect(shell.sync.lastAt).toBeDefined();
  expect(shell.sync.busy).toBe(false);
  expect(mockDataChanged).toHaveBeenCalled();
  expect(mockToast).toHaveBeenCalledWith({ kind: "success", text: "Sent 2. Not accepted 0. Still on this phone 0." });
});

it("a failed send is an error toast with its Ref, and the result line has no Ref", async () => {
  mockSync.mockRejectedValueOnce(new Error("down"));
  await mount();
  await act(async () => { await shell.sendNow(); });
  expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "err:Error: down\nRef: x" });
  expect(shell.sync.result).toBe("err:Error: down");
  expect(mockReload).toHaveBeenCalled();
  expect(mockDataChanged).not.toHaveBeenCalled();
});

it("Refresh downloads reference data, forms and cases", async () => {
  await mount();
  await act(async () => { await shell.refreshNow(); });
  expect(mockRefreshReference).toHaveBeenCalledWith("u1", { db: true }, { force: true });
  expect(mockRefreshDefs).toHaveBeenCalledWith("u1", { db: true }, { projects: [] });
  expect(mockRefreshCases).toHaveBeenCalledWith("u1", { db: true });
  expect(shell.sync.result).toBe("Refreshed.");
});

it("opens and closes one sheet at a time", async () => {
  await mount();
  act(() => shell.openSheet("sync"));
  expect(shell.sheet).toBe("sync");
  act(() => shell.openSheet("help"));
  expect(shell.sheet).toBe("help");
  act(() => shell.closeSheet());
  expect(shell.sheet).toBeNull();
});

it("Send now offline is a calm toast and no request", async () => {
  mockOffline = true;
  await mount();
  await act(async () => { await shell.sendNow(); });
  expect(mockSync).not.toHaveBeenCalled();
  expect(mockToast).toHaveBeenCalledWith({ kind: "info", text: "You're offline. Your work is saved and will send when you're back online." });
  expect(shell.sync.result).toBeUndefined();
});
