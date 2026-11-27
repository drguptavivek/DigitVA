import React from "react";
import { act, create } from "react-test-renderer";
import { AppState, Linking } from "react-native";

let mockUnlocked = true;
let mockState: {
  accounts: Array<{ user_id: string; name: string; collection_access: boolean; registered_deaths_access: boolean }>;
  lockVersion: number;
  lockNow: jest.Mock<Promise<boolean>, []>;
  reload: () => Promise<void>;
};
const mockRouter = { replace: jest.fn(), push: jest.fn() };
const mockLoad = jest.fn();
const mockCaseDetail = jest.fn();

jest.mock("expo-router", () => ({
  useRouter: () => mockRouter,
  useFocusEffect: (callback: () => void | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(() => {
      const cleanup = callback();
      return cleanup;
    }, [callback]);
  },
}));
jest.mock("../src/AppState", () => ({ useAppState: () => mockState }));
const mockSignOut = jest.fn(async (_userId: string) => undefined);
jest.mock("../src/auth", () => ({ signOut: (userId: string) => mockSignOut(userId) }));
jest.mock("../src/signOutConfirm", () => ({ confirmSignOut: async (_userId: string, onConfirmed: () => void) => onConfirmed() }));
jest.mock("../src/deathRegistrationApi", () => ({
  getNativeRegisteredDeaths: (...args: unknown[]) => mockLoad(...args),
  getNativeRegistrationCase: (...args: unknown[]) => mockCaseDetail(...args),
}));
jest.mock("../src/interviewerDb", () => ({ isUnlocked: () => mockUnlocked }));
jest.mock("../src/i18n", () => ({
  t: (key: string, params?: Record<string, unknown>) => (params ? `${key}:${Object.values(params).join(",")}` : key),
  uiLanguageTag: () => "en",
}));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) =>
      ReactActual.createElement("button", { label, onPress }),
    Row: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("row", null, children),
    Screen: ({ children }: { children: React.ReactNode }) => ReactActual.createElement("screen", null, children),
    useUiStyles: () => ({ text: {}, muted: {}, error: {}, card: {} }),
  };
});

import RegisteredDeaths from "../src/nativeRoutes/RegisteredDeaths";
import { deathStateBadge, REPORTED_CLOSED_STATES, REPORTED_INTERVIEWED_STATES, REPORTED_REFUSED_STATES } from "../src/ui/interviewRows";
import { parseRegisteredDeathPage } from "../src/api";

beforeEach(() => {
  Object.defineProperty(AppState, "currentState", { configurable: true, value: "active" });
  mockUnlocked = true;
  mockRouter.replace.mockClear();
  mockRouter.push.mockClear();
  mockLoad.mockReset();
  mockSignOut.mockClear();
  mockState = {
    accounts: [{ user_id: "u1", name: "Worker", collection_access: false, registered_deaths_access: true }],
    lockVersion: 0,
    lockNow: jest.fn(async () => {
      mockUnlocked = false;
      mockState.lockVersion += 1;
      return true;
    }),
    reload: jest.fn(async () => undefined),
  };
});

it("discards a pending page when the reporter locks and never renders its PII", async () => {
  let resolvePage!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  mockLoad.mockReturnValue(new Promise((resolve) => { resolvePage = resolve; }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
  expect(mockLoad).toHaveBeenCalledTimes(1);

  await act(async () => {
    await mockState.lockNow();
    tree.update(<RegisteredDeaths userId="u1" registeredMine={false} />);
  });
  await act(async () => {
    resolvePage({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Private Name" }], next_cursor: "next" });
    await Promise.resolve();
  });

  expect(JSON.stringify(tree.toJSON())).not.toContain("Private Name");
  expect(mockLoad).toHaveBeenCalledTimes(1);
  await act(async () => tree.unmount());
});

it("opens an own-list correction with its bounded page cursor and source", async () => {
  mockLoad
    .mockResolvedValueOnce({ deaths: [], next_cursor: "cursor-1" })
    .mockResolvedValueOnce({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "Asha" }], next_cursor: null });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
  await act(async () => { await Promise.resolve(); });
  await act(async () => tree.root.findByProps({ label: "loadMore" }).props.onPress());
  await act(async () => { await Promise.resolve(); });
  await act(async () => tree.root.findByProps({ label: "editRegistration" }).props.onPress());
  expect(mockRouter.push).toHaveBeenCalledWith({
    pathname: "/register",
    params: { userId: "u1", deathId: "d1", registrationSource: "mine", registrationCursor: "cursor-1" },
  });
  expect(mockLoad).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("hides one reporter's rows immediately and ignores its pending page after an account switch", async () => {
  let resolveFirst!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  let resolveSecond!: (page: { deaths: Array<{ death_id: string; unique_id: string; deceased_name: string }>; next_cursor: string | null }) => void;
  mockLoad
    .mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve; }))
    .mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
  mockState.accounts.push({ user_id: "u2", name: "Other worker", collection_access: false, registered_deaths_access: true });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
  expect(mockLoad).toHaveBeenCalledTimes(1);

  await act(async () => tree.update(<RegisteredDeaths userId="u2" registeredMine={false} />));
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");
  expect(mockLoad).toHaveBeenCalledTimes(2);

  await act(async () => {
    resolveFirst({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: "First worker's death" }], next_cursor: "old-cursor" });
    await Promise.resolve();
  });
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");

  await act(async () => {
    resolveSecond({ deaths: [{ death_id: "d2", unique_id: "U2", deceased_name: "Second worker's death" }], next_cursor: null });
    await Promise.resolve();
  });
  expect(JSON.stringify(tree.toJSON())).toContain("Second worker's death");
  expect(JSON.stringify(tree.toJSON())).not.toContain("First worker's death");
  await act(async () => tree.unmount());
});

it("keeps the list through a trip to the background and rereads it in place on return, no skeleton (digitva-fmz0)", async () => {
  let change!: (state: string) => void;
  const original = AppState.addEventListener;
  AppState.addEventListener = ((_event: string, handler: (state: string) => void) => {
    change = handler;
    return { remove: jest.fn() };
  }) as never;
  const page = (name: string) => ({ deaths: [{ death_id: "d1", unique_id: "U1", deceased_name: name }], next_cursor: null });
  let resolveSecond!: (value: ReturnType<typeof page>) => void;
  mockLoad.mockResolvedValueOnce(page("Kept Name")).mockReturnValueOnce(new Promise((resolve) => { resolveSecond = resolve; }));
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
  expect(JSON.stringify(tree.toJSON())).toContain("Kept Name");

  await act(async () => change("background"));
  expect(JSON.stringify(tree.toJSON())).toContain("Kept Name");
  await act(async () => change("active"));
  expect(JSON.stringify(tree.toJSON())).toContain("Kept Name"); // while the reread is in flight
  await act(async () => { resolveSecond(page("Fresh Name")); await new Promise((resolve) => setTimeout(resolve, 0)); });
  expect(JSON.stringify(tree.toJSON())).toContain("Fresh Name");
  expect(mockLoad).toHaveBeenCalledTimes(2);
  AppState.addEventListener = original;
  await act(async () => tree.unmount());
});

describe("sign-out (reporter without collection access)", () => {
  async function pressSignOut() {
    mockLoad.mockResolvedValue({ deaths: [], next_cursor: null });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={false} />); });
    await act(async () => { tree.root.findByProps({ label: "signOut" }).props.onPress(); await Promise.resolve(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    return tree;
  }

  it("locks every store before signing out, then goes Home", async () => {
    const tree = await pressSignOut();
    expect(mockState.lockNow).toHaveBeenCalledTimes(1);
    expect(mockSignOut).toHaveBeenCalledWith("u1");
    expect(mockState.lockNow.mock.invocationCallOrder[0]).toBeLessThan(mockSignOut.mock.invocationCallOrder[0]);
    expect(mockRouter.replace).toHaveBeenCalledWith("/");
    await act(async () => tree.unmount());
  });

  it("signs nobody out and says so when the stores could not be locked", async () => {
    mockState.lockNow.mockResolvedValueOnce(false);
    const tree = await pressSignOut();
    expect(mockState.lockNow).toHaveBeenCalledTimes(1);
    expect(mockSignOut).not.toHaveBeenCalled();
    expect(JSON.stringify(tree.toJSON())).toContain("errGeneric");
    await act(async () => tree.unmount());
  });
});

describe("reported death cards", () => {
  const death = (extra = {}) => ({
    death_id: "d1", unique_id: "PHC01-000274_1", project_id: "P1", state: "registered", deceased_name: "Asha", age_years: 61,
    deceased_sex: "female", date_of_death: "2026-07-01", unit_name: "SC-AAM 1", ...extra,
  });
  async function open(deaths: unknown[]) {
    mockLoad.mockResolvedValue({ deaths, next_cursor: null });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
    await act(async () => { await Promise.resolve(); });
    return tree;
  }
  const icons = (tree: ReturnType<typeof create>, label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function");

  it("shows the card with a copy icon, the area on the ID line, and no Lock now or My interviews button", async () => {
    const tree = await open([death()]);
    expect(tree.root.findAllByProps({ label: "newDeath" }).length).toBeGreaterThan(0); // the screen rendered
    expect(JSON.stringify(tree.toJSON())).toContain("Asha");
    expect(JSON.stringify(tree.toJSON())).toContain("queueCaseNumber:000274 · SC-AAM 1");
    expect(icons(tree, "queueCopyDetails:queueCaseNumber:000274")).toHaveLength(1);
    expect(tree.root.findAllByProps({ label: "lockNow" })).toHaveLength(0);
    expect(tree.root.findAllByProps({ label: "worklistTitle" })).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("dials the row's own informant number (the reporter list's shape) without a fetch or showing it", async () => {
    const openURL = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    const tree = await open([death({ informant_phone: "98765 43210" })]);
    expect(icons(tree, "callInformant")).toHaveLength(1);
    expect(JSON.stringify(tree.toJSON())).not.toContain("43210");
    await act(async () => { icons(tree, "callInformant")[0].props.onPress(); });
    expect(openURL).toHaveBeenCalledWith("tel:9876543210");
    expect(mockCaseDetail).not.toHaveBeenCalled();
    openURL.mockRestore();
    await act(async () => tree.unmount());
    const none = await open([death()]);
    expect(icons(none, "queueCopyDetails:queueCaseNumber:000274")).toHaveLength(1);
    expect(icons(none, "callInformant")).toHaveLength(0);
    await act(async () => none.unmount());
  });

  it("shows only the year for a year-only date of death", async () => {
    const tree = await open([death({ date_of_death_year_only: true })]);
    expect(tree.root.findAllByProps({ testID: "case-fact-died" })[0].props.children).toBe("metaDied:2026");
    await act(async () => tree.unmount());
  });
});

describe("search and chips (digitva-aunm)", () => {
  const row = (id: string, status = "registered") => ({ death_id: id, unique_id: id.toUpperCase(), status });
  const counts = { all: 5, waiting: 3, interviewed: 2 };
  const text = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());

  beforeEach(() => { jest.useFakeTimers(); });
  afterEach(() => { jest.useRealTimers(); });

  it("shows counts on the chips and sends the stage, from the first page, keeping it for load more", async () => {
    mockLoad.mockImplementation(async (_user, _mine, cursor) => ({ deaths: [row(cursor ? "d2" : "d1")], next_cursor: "c1", counts }));
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
    expect(mockLoad).toHaveBeenLastCalledWith("u1", true, undefined, undefined, {});
    for (const label of ["deathsChipAll · 5", "badgeWaitingInterview · 3", "badgeInterviewed · 2"]) {
      expect(tree.root.findAllByProps({ label })).not.toHaveLength(0);
    }
    await act(async () => tree.root.findByProps({ label: "loadMore" }).props.onPress());
    expect(mockLoad).toHaveBeenLastCalledWith("u1", true, "c1", undefined, {});
    await act(async () => tree.root.findByProps({ label: "badgeInterviewed · 2" }).props.onPress());
    expect(mockLoad).toHaveBeenLastCalledWith("u1", true, undefined, undefined, { stage: "interviewed" });
    await act(async () => tree.root.findByProps({ label: "loadMore" }).props.onPress());
    expect(mockLoad).toHaveBeenLastCalledWith("u1", true, "c1", undefined, { stage: "interviewed" });
    await act(async () => tree.unmount());
  });

  it("sends the search after the debounce, from the first page, and shows the no-match message", async () => {
    mockLoad.mockResolvedValueOnce({ deaths: [row("d1")], next_cursor: "c1", counts })
      .mockResolvedValue({ deaths: [], next_cursor: null, counts });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
    const input = tree.root.findByProps({ placeholder: "searchCaseId" });
    await act(async () => input.props.onChangeText("  zz9 "));
    expect(mockLoad).toHaveBeenCalledTimes(1);  // not yet
    await act(async () => { jest.advanceTimersByTime(300); });
    expect(mockLoad).toHaveBeenCalledTimes(2);
    expect(mockLoad).toHaveBeenLastCalledWith("u1", true, undefined, undefined, { q: "zz9" });
    expect(text(tree)).toContain("stateNoDeathsMatchTitle");
    expect(text(tree)).not.toContain("stateNoDeathsTitle");
    await act(async () => tree.unmount());
  });

  it("shows no counts for an older server that sends none", async () => {
    mockLoad.mockResolvedValue({ deaths: [row("d1")], next_cursor: null });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
    expect(tree.root.findAllByProps({ label: "badgeInterviewed" })).not.toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("drops a slower answer of an earlier filter", async () => {
    let resolveAll!: (page: unknown) => void;
    let resolveFresh!: (page: unknown) => void;
    mockLoad.mockReturnValueOnce(new Promise((resolve) => { resolveAll = resolve; }))
      .mockReturnValueOnce(new Promise((resolve) => { resolveFresh = resolve; }));
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<RegisteredDeaths userId="u1" registeredMine={true} />); });
    await act(async () => tree.root.findByProps({ label: "badgeInterviewed" }).props.onPress());
    expect(mockLoad).toHaveBeenCalledTimes(2);  // both loads in flight
    await act(async () => { resolveFresh({ deaths: [row("fresh", "submitted")], next_cursor: null, counts }); await Promise.resolve(); });
    await act(async () => { resolveAll({ deaths: [row("stale")], next_cursor: "old", counts }); await Promise.resolve(); });
    expect(text(tree)).toContain("FRESH");
    expect(text(tree)).not.toContain("STALE");
    expect(tree.root.findAllByProps({ label: "loadMore" })).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("badges exactly the statuses the Interviewed chip holds, the server's set", () => {
    expect([...REPORTED_INTERVIEWED_STATES]).toEqual(["submitted"]);
    expect([...REPORTED_CLOSED_STATES].sort()).toEqual(["cancelled", "duplicate"]);
    expect(deathStateBadge("submitted").label).toBe("badgeInterviewed");
    for (const status of ["duplicate", "cancelled"]) expect(deathStateBadge(status).label).toBe("badgeClosed");
    expect([...REPORTED_REFUSED_STATES]).toEqual(["refused"]);
    expect(deathStateBadge("refused").label).toBe("state_refused");
    for (const status of ["registered", "scheduled", "in_progress", "paused", "not_reachable", ""]) {
      expect(deathStateBadge(status).label).toBe("badgeWaitingInterview");
    }
  });

  it("validates counts: kept when numeric, absent is fine, malformed is refused", () => {
    const page = { deaths: [], next_cursor: null };
    expect(parseRegisteredDeathPage({ ...page, counts }).counts).toEqual(counts);
    expect(parseRegisteredDeathPage(page).counts).toBeUndefined();
    expect(() => parseRegisteredDeathPage({ ...page, counts: { all: "1", waiting: 0, interviewed: 0 } })).toThrow();
    expect(() => parseRegisteredDeathPage({ ...page, counts: { all: 1, waiting: 0 } })).toThrow();
  });
});
