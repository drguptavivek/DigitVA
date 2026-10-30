/** The phone shell: tabs by access, when the chrome shows, the account menu, Help (offline) and the Sync sheet. */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Linking, View } from "react-native";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

const mockRouter = { replace: jest.fn(), push: jest.fn() };
let mockPathname = "/worklist";
let mockParams: Record<string, string> = { userId: "u1" };
const mockLockNow = jest.fn(async () => true);
const mockChooseLocale = jest.fn(async () => undefined);
const mockReload = jest.fn(async () => undefined);
const mockSyncAccount = jest.fn(async (_userId: string, _db: unknown) => ({ sync: { sent: 1, failed: 0, remaining: 0 } }));
const mockOpenInterviewerDb = jest.fn(async (_userId: string) => ({}));
const mockUnsentWork = jest.fn(async (_userId: string) => ({ unsent: 0, attention: 0, inProgress: 0, items: [] }));
const mockRefreshReferenceData = jest.fn(async (_userId: string, _db: unknown, _options?: unknown) => ({}));
const mockRefreshAuthorizedProjectDefinitions = jest.fn(async (_userId: string, _db: unknown, _fresh: unknown) => undefined);
const mockRefreshCases = jest.fn(async (_userId: string, _db: unknown) => undefined);
const mockConfirmSignOut = jest.fn(async (_userId: string, onConfirmed: () => void) => onConfirmed());
const mockSignOut = jest.fn(async (_userId: string) => undefined);
let mockAccount: Record<string, unknown> = { user_id: "u1", name: "Asha Sharma", collection_access: true, registration_access: true, coding_access: true, reviewing_access: true };
let mockIsUnlocked = true;

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
    lockVersion: 0,
    offline: false,
    syncAccount: (userId: string, db: unknown) => mockSyncAccount(userId, db),
    device: { device_id: "d1", server: "https://va.example.org/", project_id: "p", project_name: "Hamirpur" },
    uiLocale: "en",
    chooseUiLocale: mockChooseLocale,
    lockNow: mockLockNow,
    reload: mockReload,
  }),
}));
jest.mock("../src/auth", () => ({ signOut: (userId: string) => mockSignOut(userId) }));
jest.mock("../src/signOutConfirm", () => ({ confirmSignOut: (userId: string, cb: () => void) => mockConfirmSignOut(userId, cb) }));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockIsUnlocked, openInterviewerDb: (userId: string) => mockOpenInterviewerDb(userId), unsentWork: (userId: string) => mockUnsentWork(userId) }));
jest.mock("../src/sync", () => ({
  refreshAuthorizedProjectDefinitions: (userId: string, db: unknown, fresh: unknown) => mockRefreshAuthorizedProjectDefinitions(userId, db, fresh),
  refreshCases: (userId: string, db: unknown) => mockRefreshCases(userId, db),
  refreshReferenceData: (userId: string, db: unknown, options: unknown) => mockRefreshReferenceData(userId, db, options),
}));
let mockCanTryDoris = false;
jest.mock("../src/dorisDemoAccess", () => ({ canTryDorisDemo: () => mockCanTryDoris }));
jest.mock("../src/network", () => ({ isOffline: () => false, OfflineError: class OfflineError extends Error {} }));
jest.mock("../src/errorLogDb", () => ({ installErrorLog: jest.fn() }));
jest.mock("../src/errorLog", () => ({ flushErrors: jest.fn(), setErrorRoute: jest.fn() }));
jest.mock("../src/notificationState", () => ({ readNotificationState: jest.fn(async () => undefined) }));
jest.mock("../src/updateCheck", () => ({ checkForUpdateDaily: jest.fn(async () => undefined) }));
const mockToast = jest.fn();
jest.mock("../src/toast", () => ({ useToast: () => ({ show: mockToast }) }));

import { activeNativeTab, nativeTabs, showNativeHeader, showNativeTabs } from "../src/nativeShell/navAdapter";
import { FAQ } from "../src/nativeShell/faq";
import { HELP_SLUGS, helpContent, helpGuideUrl, helpScreenFor, type HelpScreen } from "../src/nativeShell/helpContent";
import { SCREEN_HELP_CONFIG } from "../src/web/ContextualHelp";
import { initials, LanguageButton, syncIndicator, NativeHeader, NativeTabs } from "../src/nativeShell/NativeChrome";
import { AccountSheet, HelpSheet, SyncSheet } from "../src/nativeShell/sheets";
import { ShellProvider } from "../src/nativeShell/shell";
import { ShellContext, useShell, type Shell } from "../src/nativeShell/shellContext";
import { setUiLocale } from "../src/i18n";

const SYNC = { work: { unsent: 3, attention: 0, inProgress: 2, items: [] }, lastAt: new Date(2026, 9, 23, 14, 5).getTime(), busy: false, result: undefined, offline: false };
const shellValue = (patch: Partial<Shell> = {}): Shell => ({
  sheet: null, openSheet: jest.fn(), closeSheet: jest.fn(), userId: "u1", server: "https://va.example.org/", sync: SYNC,
  sendNow: jest.fn(async () => undefined), recount: jest.fn(async () => undefined), refreshNow: jest.fn(async () => undefined), header: true, tabs: true, ...patch,
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
  mockSyncAccount.mockClear();
  mockOpenInterviewerDb.mockClear();
  mockUnsentWork.mockClear();
  mockRefreshReferenceData.mockClear();
  mockRefreshAuthorizedProjectDefinitions.mockClear();
  mockRefreshCases.mockClear();
  mockAccount = { user_id: "u1", name: "Asha Sharma", collection_access: true, registration_access: true, coding_access: true, reviewing_access: true };
  mockIsUnlocked = true;
  mockCanTryDoris = false;
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
  it("keeps standalone Home and Interviews local and omits enrolled tabs", () => {
    const tabs = nativeTabs({ standalone: true });
    expect(tabs).toEqual([
      { key: "home", labelKey: "home", route: "/standalone" },
      { key: "interviews", labelKey: "tabInterviews", route: "/standalone", params: { view: "interviews" } },
    ]);
    expect(activeNativeTab("/standalone", {})).toBe("home");
    expect(activeNativeTab("/standalone", { view: "interviews" })).toBe("interviews");
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
  it("shows only a spinner while syncing or Offline, otherwise nothing in the header", () => {
    expect(syncIndicator(SYNC)).toBeUndefined();
    expect(syncIndicator({ ...SYNC, busy: true })).toEqual({ label: en.syncChipSyncing, busy: true });
    expect(syncIndicator({ ...SYNC, offline: true })).toEqual({ label: "Offline", busy: false });
  });
  it("takes initials from the first two words", () => {
    expect(initials("Asha Devi Sharma")).toBe("AD");
    expect(initials("")).toBe("?");
  });
  it("opens the Sync, Help and Account sheets from the header", async () => {
    const value = shellValue();
    const tree = await render(<NativeHeader />, value);
    expect(texts(tree)).not.toMatch(/unsent/i); // the count is not in the header
    expect(byLabel(tree, "Syncing…")).toHaveLength(0); // idle: no indicator at all
    await press(tree, "Help");
    await press(tree, "Account");
    expect(value.openSheet).toHaveBeenNthCalledWith(1, "help");
    expect(value.openSheet).toHaveBeenNthCalledWith(2, "account");
  });
  it("shows the sync indicator only while syncing or offline, and it opens the Sync sheet", async () => {
    const busy = shellValue({ sync: { ...SYNC, busy: true } });
    const tree = await render(<NativeHeader />, busy);
    await press(tree, "Syncing…");
    expect(busy.openSheet).toHaveBeenCalledWith("sync");
    const offline = await render(<NativeHeader />, shellValue({ sync: { ...SYNC, offline: true } }));
    expect(byLabel(offline, "Offline").length).toBeGreaterThan(0);
  });
  it("opens a language menu from the header button (48dp, labelled) and switches only on a choice, also before sign-in", async () => {
    const tree = await render(<NativeHeader />, shellValue());
    const label = "App language: English. Choose a language";
    expect(byLabel(tree, label)[0].props.style).toMatchObject({ width: 48, height: 48 });
    expect(byLabel(tree, "हिन्दी")).toHaveLength(0);
    await press(tree, label);
    expect(mockChooseLocale).not.toHaveBeenCalled();
    expect(byLabel(tree, "English")[0].props.accessibilityState).toEqual({ selected: true });
    expect(byLabel(tree, "हिन्दी")[0].props.accessibilityState).toEqual({ selected: false });
    await press(tree, "English");
    expect(mockChooseLocale).not.toHaveBeenCalled();
    expect(byLabel(tree, "हिन्दी")).toHaveLength(0);
    await press(tree, label);
    await press(tree, "हिन्दी");
    expect(mockChooseLocale).toHaveBeenCalledWith("hi");
    expect(byLabel(tree, "हिन्दी")).toHaveLength(0);
    mockPathname = "/sign-in";
    mockChooseLocale.mockClear();
    const pre = await render(<NativeHeader />, shellValue());
    expect(byLabel(pre, "Help")).toHaveLength(0);
    expect(byLabel(pre, "Account")).toHaveLength(0);
    await press(pre, label);
    await press(pre, "Cancel");
    expect(byLabel(pre, "हिन्दी")).toHaveLength(0);
    await press(pre, label);
    await press(pre, "हिन्दी");
    expect(mockChooseLocale).toHaveBeenCalledWith("hi");
    mockPathname = "/worklist";
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
    await press(tree, "Register");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/register", params: { userId: "u1" } });
    await press(tree, "Sync, 3 unsent");
    expect(value.openSheet).toHaveBeenCalledWith("sync");
    expect(texts(tree)).not.toMatch(/coding|review/i);
  });
  it("keeps tab labels on one line and fits them to the tab width", async () => {
    const tree = await render(<NativeTabs />, shellValue());
    const labels = tree.root.findAll((n) => n.props.numberOfLines === 1 && n.props.adjustsFontSizeToFit === true);
    expect(labels.length).toBeGreaterThanOrEqual(3);
    for (const label of labels) {
      expect(label.props.minimumFontScale).toBeGreaterThanOrEqual(0.92);
      expect(label.props.style).toMatchObject({ includeFontPadding: false, alignSelf: "stretch" });
    }
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
  it("runs Settings, Help, Lock now, Switch profile and language", async () => {
    const value = shellValue({ sheet: "account" });
    const tree = await render(<AccountSheet />, value);
    await press(tree, "Settings");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/settings", params: { userId: "u1" } });
    await press(tree, "Help");
    expect(value.openSheet).toHaveBeenCalledWith("help");
    await press(tree, "Lock now");
    expect(mockLockNow).toHaveBeenCalled();
    mockLockNow.mockClear();
    await press(tree, "Switch profile");
    // Switching profile locks (saving open work) before showing the profiles list.
    expect(mockLockNow).toHaveBeenCalledTimes(1);
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
    await press(tree, "हिन्दी");
    expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  });
  it("signs out through the confirmation, locking the stores first", async () => {
    mockLockNow.mockClear();
    const tree = await render(<AccountSheet />, shellValue({ sheet: "account" }));
    await press(tree, "Sign out");
    expect(mockConfirmSignOut).toHaveBeenCalledWith("u1", expect.any(Function));
    expect(mockLockNow).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledWith("u1");
    expect(mockLockNow.mock.invocationCallOrder[0]).toBeLessThan(mockSignOut.mock.invocationCallOrder[0]);
    expect(mockReload).toHaveBeenCalled();
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
  });
  it("signs nobody out, and shows nothing but a message, when the stores could not be locked", async () => {
    mockLockNow.mockClear();
    mockSignOut.mockClear();
    mockRouter.replace.mockClear();
    mockToast.mockClear();
    mockLockNow.mockResolvedValueOnce(false);
    const tree = await render(<AccountSheet />, shellValue({ sheet: "account" }));
    await press(tree, "Sign out");
    expect(mockLockNow).toHaveBeenCalledTimes(1);
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "Something went wrong. Try again." });

    mockToast.mockClear();
    mockLockNow.mockResolvedValueOnce(false);
    await press(tree, "Switch profile");
    expect(mockRouter.replace).not.toHaveBeenCalled();
    expect(mockToast).toHaveBeenCalledWith({ kind: "error", text: "Something went wrong. Try again." });
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
  it("keeps bundled help and FAQs available without opening the retained server guide", async () => {
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    try {
      const tree = await render(<HelpSheet />, shellValue({ sheet: "help", server: undefined }));
      expect(texts(tree)).toContain(en.help_worklist_what);
      expect(texts(tree)).toContain(en.faq_language_q);
      expect(byLabel(tree, en.helpOpenGuide)).toHaveLength(0);
      expect(open).not.toHaveBeenCalled();
    } finally {
      open.mockRestore();
    }
  });
});

describe("Try DORIS (Collect Plus)", () => {
  const tryLabel = en.helpTryDoris;
  it("Help offers the offline demo in Collect Plus, and it opens without an account", async () => {
    mockCanTryDoris = true;
    mockParams = {};
    mockPathname = "/";
    const value = shellValue({ sheet: "help", userId: undefined, server: undefined });
    const tree = await render(<HelpSheet />, value);
    await press(tree, tryLabel);
    expect(value.closeSheet).toHaveBeenCalled();
    expect(mockRouter.push).toHaveBeenCalledWith("/doris-demo");
  });
  it("plain Collect and the web do not offer it", async () => {
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(byLabel(tree, tryLabel)).toHaveLength(0);
  });
  it("is not offered over an open form or on the demo itself", async () => {
    mockCanTryDoris = true;
    for (const path of ["/form", "/revision", "/doris-demo"]) {
      mockPathname = path;
      const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
      expect(byLabel(tree, tryLabel)).toHaveLength(0);
    }
  });
  it("the header keeps Help on the sign-in, lock and enrolment screens in Collect Plus only", async () => {
    for (const path of ["/sign-in", "/unlock", "/enrol", "/pin-setup"]) {
      mockPathname = path;
      mockCanTryDoris = false;
      expect(byLabel(await render(<NativeHeader />, shellValue()), "Help")).toHaveLength(0);
      mockCanTryDoris = true;
      const plus = await render(<NativeHeader />, shellValue({ userId: undefined }));
      expect(byLabel(plus, "Help")).toHaveLength(1);
      expect(byLabel(plus, "Account")).toHaveLength(0);
    }
  });
});

describe("Help before the PIN", () => {
  const accountButtons = (tree: ReactTestRenderer) => byLabel(tree, "Open account menu");
  const faqSearch = async (tree: ReactTestRenderer, text: string) => {
    const input = tree.root.findAll((n) => n.props.accessibilityLabel === "Search questions" && typeof n.props.onChangeText === "function")[0];
    await act(async () => { input.props.onChangeText(text); });
  };

  it("offers no account, sync, settings or worklist button while the account's store is locked", async () => {
    mockPathname = "/unlock";
    mockCanTryDoris = true;
    mockIsUnlocked = false;
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    // The Help sheet itself is rendered (guide text, FAQ, the demo button) before the absences are asserted.
    expect(texts(tree)).toContain(en.faqTitle);
    expect(byLabel(tree, en.helpTryDoris)).toHaveLength(1);
    // All answers whose text is opened by the search show; none carries a go button.
    await faqSearch(tree, "a");
    expect(tree.root.findAll((n) => n.props.testID === "faq-entry" && n.type === View).length).toBeGreaterThan(0);
    await faqSearch(tree, "app language");
    expect(texts(tree)).toContain(en.faq_language_a);
    for (const label of ["Open account menu", "Open Sync", "Open Settings", "Open Drafts", "Open Sent"]) expect(byLabel(tree, label)).toHaveLength(0);
    for (const query of ["Where do I see errors", "error log to support", "continue an interview", "forms I have sent"]) {
      await faqSearch(tree, query);
      for (const label of ["Open Sync", "Open Settings", "Open Drafts", "Open Sent"]) expect(byLabel(tree, label)).toHaveLength(0);
    }
  });

  it("offers them once that account is unlocked", async () => {
    mockPathname = "/worklist";
    mockIsUnlocked = true;
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(texts(tree)).toContain(en.faqTitle);
    await faqSearch(tree, "app language");
    expect(accountButtons(tree)).toHaveLength(1);
    await faqSearch(tree, "Where do I see errors");
    expect(byLabel(tree, "Open Sync")).toHaveLength(1);
  });

  it("offers none when no account is named", async () => {
    mockPathname = "/sign-in";
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help", userId: undefined }));
    expect(texts(tree)).toContain(en.faqTitle);
    await faqSearch(tree, "app language");
    expect(texts(tree)).toContain(en.faq_language_a);
    expect(accountButtons(tree)).toHaveLength(0);
  });
});

describe("sync sheet", () => {
  it("shows last synced, unsent and the last result, and runs Send now and Refresh", async () => {
    const value = shellValue({ sheet: "sync", sync: { ...SYNC, result: "Sent 3. Not accepted 0. Still on this phone 0." } });
    const tree = await render(<SyncSheet />, value);
    const out = texts(tree);
    expect(out).toContain("Synced 14:05");
    expect(out).toContain("3 ready to send from this phone");
    expect(out).toContain("Last result: Sent 3.");
    await press(tree, "Send now");
    await press(tree, "Refresh");
    expect(value.sendNow).toHaveBeenCalledTimes(1);
    expect(value.refreshNow).toHaveBeenCalledTimes(1);
  });
  it("offers neither Send now nor Refresh while the account is locked", async () => {
    const unlockedTree = await render(<SyncSheet />, shellValue({ sheet: "sync" }));
    expect(byLabel(unlockedTree, "Send now")).toHaveLength(1);
    mockIsUnlocked = false;
    const tree = await render(<SyncSheet />, shellValue({ sheet: "sync" }));
    expect(byLabel(tree, "Send now")).toHaveLength(0);
    expect(byLabel(tree, "Refresh")).toHaveLength(0);
  });
  it("lists each unsent item with its state and last error, and links to the drafts in progress", async () => {
    const work = {
      unsent: 1, attention: 1, inProgress: 2,
      items: [
        { key: "d:1", kind: "interview" as const, title: "Ramesh Kumar", state: "attention" as const, error: "HTTP 409 answers_conflict POST /intake/submissions" },
        { key: "r:1", kind: "registration" as const, title: "Sunita Devi", state: "ready" as const },
      ],
    };
    const value = shellValue({ sheet: "sync", sync: { ...SYNC, work } });
    const tree = await render(<SyncSheet />, value);
    const out = texts(tree);
    expect(out).toContain("Interview: Ramesh Kumar");
    expect(out).toContain("Needs attention");
    expect(out).toContain("Ref: HTTP 409 answers_conflict POST /intake/submissions");
    expect(out).toContain("Registration: Sunita Devi");
    expect(out).toContain("1 need attention");
    await press(tree, "2 in progress → Interviews");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", view: "interviews", filter: "drafts" } });
  });
  it("disables both actions while busy", async () => {
    const tree = await render(<SyncSheet />, shellValue({ sheet: "sync", sync: { ...SYNC, busy: true } }));
    expect(byLabel(tree, "Send now")[0].props.disabled).toBe(true);
    expect(byLabel(tree, "Refresh")[0].props.disabled).toBe(true);
  });
  it("keeps standalone sync local and links to its drafts and enrolment", async () => {
    mockAccount.standalone = true;
    const work = { unsent: 1, attention: 0, inProgress: 2, items: [] };
    const tree = await render(<SyncSheet />, shellValue({ sheet: "sync", sync: { ...SYNC, work } }));
    const out = texts(tree);
    expect(out).toContain(en.standaloneWarning);
    expect(byLabel(tree, "Send now")).toHaveLength(0);
    expect(byLabel(tree, "Refresh")).toHaveLength(0);
    await press(tree, "2 in progress → Interviews");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/standalone", params: { userId: "u1", view: "interviews", filter: "drafts" } });
    await press(tree, en.standaloneEnrol);
    expect(mockRouter.push).toHaveBeenCalledWith("/enrol");
  });
});

it("refuses standalone shell send and refresh before opening a database or syncing", async () => {
  mockAccount.standalone = true;
  let shell!: Shell;
  function CaptureShell() {
    shell = useShell();
    return null;
  }
  let tree!: ReactTestRenderer;
  mockPathname = "/standalone";
  await act(async () => { tree = create(<ShellProvider><CaptureShell /></ShellProvider>); });
  await act(async () => {
    await shell.sendNow();
    await shell.refreshNow();
  });
  expect(mockOpenInterviewerDb).not.toHaveBeenCalled();
  expect(mockSyncAccount).not.toHaveBeenCalled();
  expect(mockRefreshReferenceData).not.toHaveBeenCalled();
  expect(mockRefreshAuthorizedProjectDefinitions).not.toHaveBeenCalled();
  expect(mockRefreshCases).not.toHaveBeenCalled();
  expect(shell.sync.result).toBeUndefined();
  expect(mockToast).toHaveBeenCalledWith({ kind: "info", text: en.standaloneWarning });
  await act(async () => tree.unmount());
});

it("does not use another account when the shell userId is unrecognized", async () => {
  let shell!: Shell;
  function CaptureShell() {
    shell = useShell();
    return null;
  }
  let tree!: ReactTestRenderer;
  mockParams = { userId: "unrecognized" };
  await act(async () => { tree = create(<ShellProvider><CaptureShell /></ShellProvider>); });
  await act(async () => {
    await shell.sendNow();
    await shell.refreshNow();
  });
  expect(shell.userId).toBeUndefined();
  expect(mockOpenInterviewerDb).not.toHaveBeenCalled();
  expect(mockSyncAccount).not.toHaveBeenCalled();
  expect(mockRefreshReferenceData).not.toHaveBeenCalled();
  expect(mockRefreshAuthorizedProjectDefinitions).not.toHaveBeenCalled();
  expect(mockRefreshCases).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

describe("common questions (Help)", () => {
  const search = async (tree: ReactTestRenderer, text: string, label = "Search questions") => {
    const input = tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onChangeText === "function")[0];
    await act(async () => { input.props.onChangeText(text); });
  };

  it("has an answer for every question in English and Hindi", () => {
    for (const dictionary of [en, hi] as Array<Record<string, string>>) {
      for (const { id } of FAQ) {
        expect(dictionary[`faq_${id}_q`]).toBeTruthy();
        expect(dictionary[`faq_${id}_a`]).toBeTruthy();
      }
    }
    expect(FAQ.length).toBe(11);
  });

  it("lists the questions and shows an answer on tap", async () => {
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(tree.root.findAll((n) => n.props.testID === "faq-entry" && n.type === View)).toHaveLength(FAQ.length);
    expect(texts(tree)).not.toContain(en.faq_unsent_a);
    await press(tree, en.faq_unsent_q);
    expect(texts(tree)).toContain(en.faq_unsent_a);
  });

  it("searches questions and answers, and says so when nothing matches", async () => {
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    await search(tree, "clock");
    expect(tree.root.findAll((n) => n.props.testID === "faq-entry" && n.type === View)).toHaveLength(1);
    expect(texts(tree)).toContain(en.faq_clock_a);
    await search(tree, "zzzz");
    expect(texts(tree)).toContain(en.faqNone);
  });

  it("answers in Hindi", async () => {
    setUiLocale("hi");
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(texts(tree)).toContain(hi.faq_language_q);
    await search(tree, "हिन्दी", hi.faqSearch);
    expect(texts(tree)).toContain(hi.faq_language_a);
  });

  it("on a form screen the go buttons that would leave it are not offered; the sheets still are", async () => {
    for (const path of ["/form", "/revision"]) {
      mockPathname = path;
      const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
      await search(tree, "continue an interview");
      expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Open Drafts" && typeof n.props.onPress === "function")).toHaveLength(0);
      await search(tree, "error log to support");
      expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Open Settings" && typeof n.props.onPress === "function")).toHaveLength(0);
      await search(tree, "app language");
      expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Open account menu" && typeof n.props.onPress === "function")).toHaveLength(1);
    }
  });

  it("offers the full guide only when the phone has a server", async () => {
    const withServer = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(byLabel(withServer, en.helpOpenGuide)).toHaveLength(1);
    const withoutServer = await render(<HelpSheet />, shellValue({ sheet: "help", server: undefined }));
    expect(byLabel(withoutServer, en.helpOpenGuide)).toHaveLength(0);
  });

  it("does not offer the go button for the screen Help was opened on", async () => {
    mockPathname = "/worklist";
    const worklist = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    await search(worklist, "error log to support");
    expect(byLabel(worklist, "Open Settings")).toHaveLength(1);
    mockPathname = "/settings";
    const settings = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    await search(settings, "error log to support");
    expect(byLabel(settings, "Open Settings")).toHaveLength(0);
  });

  it("keeps Open Drafts on the worklist even when the address names drafts (the list may have switched in place)", async () => {
    mockParams = { userId: "u1", filter: "drafts" };
    mockPathname = "/worklist";
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    await search(tree, "continue an interview");
    expect(byLabel(tree, "Open Drafts")).toHaveLength(1);
  });

  it("standalone Help leaves out the answers about Sync and says the unsent count without Send now", async () => {
    mockAccount = { user_id: "u1", name: "Asha Sharma", standalone: true };
    mockPathname = "/worklist";
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help" }));
    expect(JSON.stringify(texts(tree))).toContain(en.help_worklist_do1);
    for (const line of [en.help_worklist_do2, en.help_worklist_do3]) expect(JSON.stringify(texts(tree))).not.toContain(line);
    expect(texts(tree)).toContain(en.helpUnsentStandalone.replace("{count}", "3"));
    expect(texts(tree)).not.toContain(en.helpUnsent.replace("{count}", "3"));
    expect(tree.root.findAll((n) => n.props.testID === "faq-entry" && n.type === View)).toHaveLength(FAQ.filter((item) => !item.enrolledOnly).length);
  });

  it("buttons open the screen the answer names", async () => {
    const closeSheet = jest.fn();
    const openSheet = jest.fn();
    const tree = await render(<HelpSheet />, shellValue({ sheet: "help", closeSheet, openSheet }));
    await search(tree, "continue an interview");
    await press(tree, "Open Drafts");
    expect(mockRouter.replace).toHaveBeenCalledWith({ pathname: "/worklist", params: { userId: "u1", view: "interviews", filter: "drafts" } });
    expect(closeSheet).toHaveBeenCalled();
    await search(tree, "forms I have sent");
    await press(tree, "Open Sent");
    expect(mockRouter.replace).toHaveBeenLastCalledWith({ pathname: "/worklist", params: { userId: "u1", view: "interviews", filter: "sent" } });
    await search(tree, "Where do I see errors");
    await press(tree, "Open Sync");
    expect(openSheet).toHaveBeenCalledWith("sync");
    await search(tree, "error log to support");
    await press(tree, "Open Settings");
    expect(mockRouter.push).toHaveBeenCalledWith({ pathname: "/settings", params: { userId: "u1" } });
    await search(tree, "app language");
    await press(tree, "Open account menu");
    expect(openSheet).toHaveBeenCalledWith("account");
  });
});
