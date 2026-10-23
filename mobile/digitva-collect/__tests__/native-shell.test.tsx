/** The phone shell: tabs by access, when the chrome shows, the account menu, Help (offline) and the Sync sheet. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Linking } from "react-native";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

const mockRouter = { replace: jest.fn(), push: jest.fn() };
let mockPathname = "/worklist";
let mockParams: Record<string, string> = { userId: "u1" };
const mockLockNow = jest.fn(async () => true);
const mockChooseLocale = jest.fn(async () => undefined);
const mockReload = jest.fn(async () => undefined);
const mockConfirmSignOut = jest.fn(async (_userId: string, onConfirmed: () => void) => onConfirmed());
const mockSignOut = jest.fn(async (_userId: string) => undefined);
let mockAccount: Record<string, unknown> = { user_id: "u1", name: "Asha Sharma", collection_access: true, registration_access: true, coding_access: true, reviewing_access: true };

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  usePathname: () => mockPathname,
  useGlobalSearchParams: () => mockParams,
}));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 16, left: 0, right: 0 }) }));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    ready: true,
    accounts: [mockAccount],
    device: { device_id: "d1", server: "https://va.example.org/", project_id: "p", project_name: "Hamirpur" },
    uiLocale: "en",
    chooseUiLocale: mockChooseLocale,
    lockNow: mockLockNow,
    reload: mockReload,
  }),
}));
jest.mock("../src/auth", () => ({ signOut: (userId: string) => mockSignOut(userId) }));
jest.mock("../src/signOutConfirm", () => ({ confirmSignOut: (userId: string, cb: () => void) => mockConfirmSignOut(userId, cb) }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => true }));

import { activeNativeTab, nativeTabs, showNativeHeader, showNativeTabs } from "../src/nativeShell/navAdapter";
import { HELP_SLUGS, helpContent, helpGuideUrl, helpScreenFor, type HelpScreen } from "../src/nativeShell/helpContent";
import { SCREEN_HELP_CONFIG } from "../src/web/ContextualHelp";
import { chipState, initials, NativeHeader, NativeTabs } from "../src/nativeShell/NativeChrome";
import { AccountSheet, HelpSheet, SyncSheet } from "../src/nativeShell/sheets";
import { ShellContext, type Shell } from "../src/nativeShell/shellContext";
import { setUiLocale } from "../src/i18n";

const SYNC = { unsent: 3, lastAt: new Date(2026, 9, 23, 14, 5).getTime(), busy: false, result: undefined, offline: false };
const shellValue = (patch: Partial<Shell> = {}): Shell => ({
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "u1", sync: SYNC,
  sendNow: jest.fn(async () => undefined), refreshNow: jest.fn(async () => undefined), header: true, tabs: true, ...patch,
});
async function render(node: React.ReactElement, value: Shell): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<ShellContext.Provider value={value}>{node}</ShellContext.Provider>); });
  return tree;
}
const byLabel = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function");
const press = async (tree: ReactTestRenderer, label: string) => {
  const target = byLabel(tree, label)[0];
  expect(target).toBeDefined();
  await act(async () => { await target.props.onPress(); });
};
const texts = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => {
  jest.clearAllMocks();
  setUiLocale("en");
  mockPathname = "/worklist";
  mockParams = { userId: "u1" };
  mockAccount = { user_id: "u1", name: "Asha Sharma", collection_access: true, registration_access: true, coding_access: true, reviewing_access: true };
});

describe("navigation adapter", () => {
  const keys = (account: Parameters<typeof nativeTabs>[0]) => nativeTabs(account).map((tab) => tab.key);
  it("offers Interviews and Register death by access, never coding or review", () => {
    expect(keys({ collection_access: true, registration_access: true })).toEqual(["home", "interviews", "register", "sync"]);
    expect(keys({ collection_access: true })).toEqual(["home", "interviews", "sync"]);
    expect(keys({ registration_access: true })).toEqual(["home", "register", "sync"]);
    expect(keys({ registered_deaths_access: true })).toEqual(["home", "sync"]);
    expect(keys(undefined)).toEqual(["home", "sync"]);
    for (const tab of nativeTabs({ collection_access: true, registration_access: true, registered_deaths_access: true })) {
      expect(`${tab.route ?? ""}`).not.toMatch(/coding|review|workspace/);
    }
  });
  it("opens Sync as a sheet, not a route", () => {
    expect(nativeTabs({ collection_access: true }).find((tab) => tab.key === "sync")?.route).toBeUndefined();
  });
  it("marks the tab a screen belongs to", () => {
    expect(activeNativeTab("/worklist", {})).toBe("home");
    expect(activeNativeTab("/worklist", { view: "interviews" })).toBe("interviews");
    expect(activeNativeTab("/register", {})).toBe("register");
    expect(activeNativeTab("/settings", {})).toBeUndefined();
  });
  it("hides the tabs on forms, pre-login screens, the accounts list, when locked and with the keyboard open", () => {
    const base = { pathname: "/worklist", userId: "u1", unlocked: true, keyboardOpen: false };
    expect(showNativeTabs(base)).toBe(true);
    for (const pathname of ["/form", "/revision", "/unlock", "/sign-in", "/enrol", "/pin-setup", "/"]) expect(showNativeTabs({ ...base, pathname })).toBe(false);
    expect(showNativeTabs({ ...base, unlocked: false })).toBe(false);
    expect(showNativeTabs({ ...base, keyboardOpen: true })).toBe(false);
    expect(showNativeTabs({ ...base, userId: undefined })).toBe(false);
  });
  it("hides the header on forms and pre-login screens only", () => {
    for (const pathname of ["/form", "/revision", "/unlock", "/sign-in", "/enrol", "/pin-setup"]) expect(showNativeHeader(pathname)).toBe(false);
    for (const pathname of ["/", "/worklist", "/register", "/settings", "/case"]) expect(showNativeHeader(pathname)).toBe(true);
  });
});

describe("header and tabs", () => {
  it("shows Synced HH:MM, a spinner while syncing, the unsent count, or Offline", () => {
    expect(chipState({ ...SYNC, unsent: 0 }).label).toBe("Synced 14:05");
    expect(chipState({ ...SYNC, unsent: 0, lastAt: undefined }).label).toBe(en.syncChipNever);
    expect(chipState(SYNC).label).toBe("3 unsent");
    expect(chipState({ ...SYNC, busy: true })).toEqual({ label: en.syncChipSyncing, tone: "busy" });
    expect(chipState({ ...SYNC, offline: true }).label).toBe("Offline");
  });
  it("takes initials from the first two words", () => {
    expect(initials("Asha Devi Sharma")).toBe("AD");
    expect(initials("")).toBe("?");
  });
  it("opens the Sync, Help and Account sheets from the header", async () => {
    const value = shellValue();
    const tree = await render(<NativeHeader />, value);
    await press(tree, "3 unsent");
    await press(tree, "Help");
    await press(tree, "Account");
    expect(value.openSheet).toHaveBeenNthCalledWith(1, "sync");
    expect(value.openSheet).toHaveBeenNthCalledWith(2, "help");
    expect(value.openSheet).toHaveBeenNthCalledWith(3, "account");
  });
  it("renders nothing when the shell says the header is off", async () => {
    const tree = await render(<NativeHeader />, shellValue({ header: false }));
    expect(tree.toJSON()).toBeNull();
  });
  it("navigates tabs with the current userId, opens Sync as a sheet, and shows the unsent badge", async () => {
    const value = shellValue();
    const tree = await render(<NativeTabs />, value);
    expect(texts(tree)).toContain('"3"');
    await press(tree, "Interviews");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", view: "interviews" } });
    await press(tree, "Register a death");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/register", params: { userId: "u1" } });
    await press(tree, "Sync, 3 unsent");
    expect(value.openSheet).toHaveBeenCalledWith("sync");
    expect(texts(tree)).not.toMatch(/coding|review/i);
  });
  it("renders no tabs while the shell hides them", async () => {
    const tree = await render(<NativeTabs />, shellValue({ tabs: false }));
    expect(tree.toJSON()).toBeNull();
  });
});

describe("account menu", () => {
  it("shows name, role and project, and the sync summary", async () => {
    const tree = await render(<AccountSheet />, shellValue({ sheet: "account" }));
    const out = texts(tree);
    expect(out).toContain("Asha Sharma");
    expect(out).toContain("Hamirpur");
    expect(out).toContain("Synced 14:05");
    expect(out).toContain("3 unsent");
    expect(out).toContain("Version ");
  });
  it("runs Settings, Help, Lock now, Switch interviewer and language", async () => {
    const value = shellValue({ sheet: "account" });
    const tree = await render(<AccountSheet />, value);
    await press(tree, "Settings");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/settings", params: { userId: "u1" } });
    await press(tree, "Help");
    expect(value.openSheet).toHaveBeenCalledWith("help");
    await press(tree, "Lock now");
    expect(mockLockNow).toHaveBeenCalled();
    await press(tree, "Switch interviewer");
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
    await press(tree, "हिन्दी");
    expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  });
  it("signs out only through the existing unsent-work confirmation", async () => {
    const tree = await render(<AccountSheet />, shellValue({ sheet: "account" }));
    await press(tree, "Sign out");
    expect(mockConfirmSignOut).toHaveBeenCalledWith("u1", expect.any(Function));
    expect(mockSignOut).toHaveBeenCalledWith("u1");
    expect(mockReload).toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
  });
});

describe("help", () => {
  const SCREENS: HelpScreen[] = ["home", "worklist", "form", "revision", "settings", "register"];
  it("has a purpose line and three steps per screen in English and Hindi, with no network", () => {
    for (const locale of ["en", "hi"] as const) {
      setUiLocale(locale);
      for (const screen of SCREENS) {
        const help = helpContent(screen, {});
        expect(help.state).toEqual([]);
        expect([help.what, ...help.todo]).toHaveLength(4);
        for (const line of [help.what, ...help.todo]) expect(line).not.toMatch(/^help_/);
        const key = `help_${screen}_what` as keyof typeof en;
        expect(help.what).toBe(locale === "hi" ? hi[key] : en[key]);
        if (locale === "hi") expect(hi[key]).not.toBe(en[key]);
      }
    }
    expect(Object.keys(hi).filter((k) => k.startsWith("help_")).sort()).toEqual(Object.keys(en).filter((k) => k.startsWith("help_")).sort());
  });
  it("adds offline and unsent-work lines first", () => {
    const help = helpContent("worklist", { offline: true, unsent: 2 });
    expect(help.state).toEqual([en.helpOffline, "2 items are waiting on this phone. Open Sync and tap Send now."]);
  });
  it("maps routes to screens and uses the browser's guide slugs", () => {
    expect(helpScreenFor("/worklist")).toBe("worklist");
    expect(helpScreenFor("/")).toBe("home");
    expect(helpScreenFor("/register")).toBe("register");
    const web = { home: "home", worklist: "collection", form: "interview", revision: "interview", settings: "settings", register: "deathRegistration" } as const;
    for (const screen of SCREENS) expect(HELP_SLUGS[screen]).toBe(SCREEN_HELP_CONFIG[web[screen]].helpSlug);
    expect(helpGuideUrl("https://va.example.org/", "/help/data-collection")).toBe("https://va.example.org/help/data-collection");
  });
  it("shows the sheet for the current screen and opens the full guide with Linking", async () => {
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    mockPathname = "/register";
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help", sync: { ...SYNC, offline: true } }));
    const out = texts(tree);
    expect(out).toContain(en.help_register_what);
    expect(out).toContain(en.helpOffline);
    await press(tree, "Open the full guide");
    expect(open).toHaveBeenCalledWith("https://va.example.org/help/data-collection");
  });
});

describe("sync sheet", () => {
  it("shows last synced, unsent and the last result, and runs Send now and Refresh", async () => {
    const value = shellValue({ sheet: "sync", sync: { ...SYNC, result: "Sent 3. Not accepted 0. Still on this phone 0." } });
    const tree = await render(<SyncSheet />, value);
    const out = texts(tree);
    expect(out).toContain("Synced 14:05");
    expect(out).toContain("3 unsent");
    expect(out).toContain("Last result: Sent 3.");
    await press(tree, "Send now");
    await press(tree, "Refresh");
    expect(value.sendNow).toHaveBeenCalledTimes(1);
    expect(value.refreshNow).toHaveBeenCalledTimes(1);
  });
  it("disables both actions while busy", async () => {
    const tree = await render(<SyncSheet />, shellValue({ sheet: "sync", sync: { ...SYNC, busy: true } }));
    expect(byLabel(tree, "Send now")[0].props.disabled).toBe(true);
    expect(byLabel(tree, "Refresh")[0].props.disabled).toBe(true);
  });
});
