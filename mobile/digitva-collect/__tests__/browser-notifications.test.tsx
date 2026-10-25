import React from "react";
import { act, create } from "react-test-renderer";

jest.mock("../src/client/session", () => ({ loadBrowserSession: jest.fn() }));
jest.mock("../src/preferences", () => ({
  ...jest.requireActual("../src/preferences"),
  getUiLocalePreference: async () => "en",
  setUiLocalePreference: async () => undefined,
}));
jest.mock("../src/i18n", () => ({ setUiLocale: (value: string) => value, t: (key: string) => key }));
jest.mock("../src/client/api", () => ({
  ...jest.requireActual("../src/client/api"),
  requestClientJson: jest.fn(),
  getIntakeContext: jest.fn(),
  getCases: jest.fn(),
  getDrafts: jest.fn(),
}));
jest.mock("../src/client/revisionList", () => ({ getSubmittedRevisions: jest.fn() }));
jest.mock("../src/AppState", () => jest.requireActual("../src/AppState.web"));
jest.mock("expo-router", () => ({ useRouter: () => ({ push: jest.fn() }), useLocalSearchParams: () => ({}) }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => <button data-label={label} onClick={onPress} />,
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ error: {}, muted: {}, headline: {}, card: {}, text: {} }),
}));
jest.mock("../src/web/common", () => ({ WebShell: ({ children }: { children: React.ReactNode }) => <>{children}</>, browserErrorText: () => "error" }));

import { AppStateProvider, useAppState } from "../src/AppState.web";
import { ApiError, getCases, getDrafts, getIntakeContext, requestClientJson } from "../src/client/api";
import { loadBrowserSession } from "../src/client/session";
import { getSubmittedRevisions } from "../src/client/revisionList";
import CollectionScreen from "../src/web/CollectionScreen";
import { ConfirmDialog } from "../src/ConfirmDialog";

const userA = {
  user: { user_id: "u1", name: "Worker" },
  csrf: { header: "X-CSRFToken", token: "csrf" },
  capabilities: { intake: true, registerDeath: true, registeredDeaths: false, coding: false, reviewing: false },
  links: { login: "/vaauth/valogin", logout: "/vaauth/valogout", intakeCases: "/api/v1/intake/cases", intakeDrafts: "/api/v1/intake/drafts" },
  access: {
    user: { user_id: "u1", name: "Worker" },
    is_admin: false,
    roles: ["interviewer"],
    demo_coding: { available: false, project_ids: [] },
    projects: [{
      project_id: "P1",
      project_name: "Project",
      has_tree: false,
      grants: [{ role: "interviewer", scope: "project", active: true, source: "assigned" }],
      sites: [{ site_id: "S1", site_name: "Site", roles: ["interviewer"] }],
      actions: {
        interview: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
        register_death: [{ site_id: "S1", site_name: "Site", web_intake_mode: "both", org_units: [] }],
      },
    }],
  },
};
const sessionA = { authenticated: true, bootstrap: userA };
const emptyPage = (after: number) => ({ notifications: [], next_cursor: after });
const notification = (id: number, kind = "future_kind") => ({
  id, kind, created_at: "2026-10-05T09:30:00+00:00", project_id: "ABC01",
  death_id: null, draft_id: null, va_sid: null,
});

let state: ReturnType<typeof useAppState>;
function Consumer() { state = useAppState(); return null; }

let windowHandlers: Record<string, Array<() => void>>;
let documentHandlers: Record<string, Array<() => void>>;
let visibilityState: DocumentVisibilityState;
let storageWrite: jest.Mock;

function installVisibilityEvents() {
  windowHandlers = {};
  documentHandlers = {};
  visibilityState = "visible";
  storageWrite = jest.fn();
  const storage = { getItem: jest.fn(), setItem: storageWrite, removeItem: jest.fn(), clear: jest.fn(), key: jest.fn(), length: 0 };
  Object.defineProperty(window, "localStorage", { configurable: true, value: storage });
  Object.defineProperty(window, "sessionStorage", { configurable: true, value: storage });
  Object.defineProperty(window, "addEventListener", { configurable: true, value: (type: string, handler: () => void) => { (windowHandlers[type] ??= []).push(handler); } });
  Object.defineProperty(window, "removeEventListener", { configurable: true, value: jest.fn() });
  Object.defineProperty(window, "clearInterval", { configurable: true, value: globalThis.clearInterval });
  Object.defineProperty(window, "setInterval", { configurable: true, value: globalThis.setInterval });
  Object.defineProperty(globalThis, "document", { configurable: true, value: {
    get visibilityState() { return visibilityState; },
    addEventListener: (type: string, handler: () => void) => { (documentHandlers[type] ??= []).push(handler); },
    removeEventListener: jest.fn(),
  } });
}

function emitVisibilityChange() {
  for (const handler of documentHandlers.visibilitychange ?? []) handler();
}

async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

async function mountProvider() {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><Consumer /></AppStateProvider>); });
  await settle();
  return tree;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-10-05T10:00:00Z"));
  jest.clearAllMocks();
  installVisibilityEvents();
  (loadBrowserSession as jest.Mock).mockResolvedValue(sessionA);
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    return emptyPage(after);
  });
  (getIntakeContext as jest.Mock).mockResolvedValue({ context: [] });
  (getCases as jest.Mock).mockResolvedValue({ cases: [], next_cursor: null });
  (getDrafts as jest.Mock).mockResolvedValue({ drafts: [] });
  (getSubmittedRevisions as jest.Mock).mockResolvedValue([]);
});

afterEach(() => {
  jest.useRealTimers();
});

it("polls immediately, respects the 30-second floor, and pauses while hidden", async () => {
  const tree = await mountProvider();
  expect(requestClientJson).toHaveBeenCalledTimes(1);

  emitVisibilityChange();
  expect(requestClientJson).toHaveBeenCalledTimes(1);
  visibilityState = "hidden";
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(requestClientJson).toHaveBeenCalledTimes(1);

  visibilityState = "visible";
  emitVisibilityChange();
  await settle();
  expect(requestClientJson).toHaveBeenCalledTimes(2);
  expect(storageWrite).not.toHaveBeenCalled();
  await act(async () => tree.unmount());
});

it("drains full pages immediately and advances across unknown kinds", async () => {
  const tree = await mountProvider();
  state.acknowledgeAuthoritativeRefresh(state.notificationGeneration);
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    if (after === 0) return { notifications: Array.from({ length: 100 }, (_, index) => notification(index + 1)), next_cursor: 100 };
    return { notifications: [notification(101)], next_cursor: 101 };
  });
  const generation = state.notificationGeneration;
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });

  expect((requestClientJson as jest.Mock).mock.calls.map(([path]) => path)).toEqual([
    "/api/v1/me/notifications?after=0",
    "/api/v1/me/notifications?after=0",
    "/api/v1/me/notifications?after=100",
  ]);
  expect(state.notificationGeneration).toBeGreaterThan(generation);
  await act(async () => tree.unmount());
});

it("treats malformed pages as doubt without advancing the cursor", async () => {
  const tree = await mountProvider();
  state.acknowledgeAuthoritativeRefresh(state.notificationGeneration);
  (requestClientJson as jest.Mock).mockResolvedValue({ notifications: [notification(9)], next_cursor: 10 });
  const generation = state.notificationGeneration;
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(state.notificationGeneration).toBeGreaterThan(generation);

  state.acknowledgeAuthoritativeRefresh(state.notificationGeneration);
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    return emptyPage(after);
  });
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect((requestClientJson as jest.Mock).mock.calls.at(-1)?.[0]).toBe("/api/v1/me/notifications?after=0");
  await act(async () => tree.unmount());
});

it("does not reread recently refreshed collections for an empty poll, then rereads after 15 minutes", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(1);
  state.acknowledgeAuthoritativeRefresh(state.notificationGeneration);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(getCases).toHaveBeenCalledTimes(1);
  await act(async () => { await jest.advanceTimersByTimeAsync(14 * 60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);
  expect(getDrafts).toHaveBeenCalledTimes(2);
  expect(getSubmittedRevisions).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("refreshes authoritative collection data when any notification arrives", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(1);
  (requestClientJson as jest.Mock).mockResolvedValue({ notifications: [notification(7)], next_cursor: 7 });

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);
  expect(getDrafts).toHaveBeenCalledTimes(2);
  expect(getSubmittedRevisions).toHaveBeenCalledTimes(2);
  expect(JSON.stringify(tree.toJSON())).not.toContain("future_kind");
  expect(JSON.stringify(tree.toJSON())).not.toContain("va_sid");
  await act(async () => tree.unmount());
});

it("retries a failed authoritative refresh on the next empty poll and stops after acknowledgement", async () => {
  let poll = 0;
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    poll += 1;
    return poll === 2
      ? { notifications: [notification(7)], next_cursor: 7 }
      : emptyPage(after);
  });
  (getCases as jest.Mock).mockImplementation(async () => {
    if ((getCases as jest.Mock).mock.calls.length === 2) throw new Error("temporary failure");
    return { cases: [], next_cursor: null };
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(1);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(3);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(getCases).toHaveBeenCalledTimes(3);
  await act(async () => tree.unmount());
});

it("retries initial and overdue periodic refresh failures on the next empty poll", async () => {
  (getCases as jest.Mock).mockImplementation(async () => {
    if ([1, 3].includes((getCases as jest.Mock).mock.calls.length)) throw new Error("temporary failure");
    return { cases: [], next_cursor: null };
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(1);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);

  await act(async () => { await jest.advanceTimersByTimeAsync(15 * 60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(3);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(4);
  await act(async () => tree.unmount());
});

it("does not start a coalesced notification refresh after the collection screen unmounts", async () => {
  const firstCases = deferred<{ cases: []; next_cursor: null }>();
  (getCases as jest.Mock).mockImplementation(() => (
    (getCases as jest.Mock).mock.calls.length === 1
      ? Promise.resolve({ cases: [], next_cursor: null })
      : firstCases.promise
  ));
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    const poll = (requestClientJson as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/me/notifications")).length;
    return poll === 2
      ? { notifications: [notification(7)], next_cursor: 7 }
      : poll === 3
        ? { notifications: [notification(8)], next_cursor: 8 }
        : emptyPage(after);
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  await act(async () => { await jest.advanceTimersByTimeAsync(120_000); });
  expect(getCases).toHaveBeenCalledTimes(2);
  await act(async () => tree.update(<AppStateProvider><Consumer /></AppStateProvider>));
  firstCases.resolve({ cases: [], next_cursor: null });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("does not carry an old account's pending notification refresh into the next account", async () => {
  const firstCases = deferred<{ cases: []; next_cursor: null }>();
  const userB = { ...userA, user: { user_id: "u2", name: "Next worker" }, access: { ...userA.access, user: { user_id: "u2", name: "Next worker" } } };
  (loadBrowserSession as jest.Mock).mockResolvedValueOnce(sessionA).mockResolvedValueOnce({ authenticated: true, bootstrap: userB });
  (getCases as jest.Mock).mockImplementation(() => (
    (getCases as jest.Mock).mock.calls.length === 2
      ? firstCases.promise
      : Promise.resolve({ cases: [], next_cursor: null })
  ));
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    if (path === userA.links.logout) return {};
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    const poll = (requestClientJson as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/me/notifications")).length;
    return poll === 2
      ? { notifications: [notification(7)], next_cursor: 7 }
      : emptyPage(after);
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(getCases).toHaveBeenCalledTimes(2);

  await act(async () => { await state.reload(); });
  await settle();
  expect(state.bootstrap?.user.user_id).toBe("u2");
  expect(getCases).toHaveBeenCalledTimes(3);

  firstCases.resolve({ cases: [], next_cursor: null });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(3);
  await act(async () => tree.unmount());
});

it("runs one coalesced follow-up when notifications arrive during an older collection refresh", async () => {
  const firstCases = deferred<{ cases: []; next_cursor: null }>();
  (getCases as jest.Mock).mockImplementation(() => (
    (getCases as jest.Mock).mock.calls.length === 1
      ? firstCases.promise
      : Promise.resolve({ cases: [], next_cursor: null })
  ));
  (requestClientJson as jest.Mock).mockImplementation(async (path: string) => {
    const after = Number(new URL(path, "https://digitva.test").searchParams.get("after"));
    if (after === 0) return { notifications: [notification(7)], next_cursor: 7 };
    if (after === 7) return { notifications: [notification(8)], next_cursor: 8 };
    return emptyPage(after);
  });
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<AppStateProvider><><Consumer /><CollectionScreen /></></AppStateProvider>); });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(1);

  await act(async () => { await jest.advanceTimersByTimeAsync(120_000); });
  firstCases.resolve({ cases: [], next_cursor: null });
  await settle();
  expect(getCases).toHaveBeenCalledTimes(2);
  expect(getDrafts).toHaveBeenCalledTimes(2);
  expect(getSubmittedRevisions).toHaveBeenCalledTimes(2);

  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  expect(getCases).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("reloads access after a poll is refused and gates immediate same-user retries", async () => {
  const tree = await mountProvider();
  (requestClientJson as jest.Mock).mockRejectedValue(new ApiError(403, "forbidden"));
  await act(async () => { await jest.advanceTimersByTimeAsync(60_000); });
  await settle();
  expect(loadBrowserSession).toHaveBeenCalledTimes(2);
  expect(state.authenticated).toBe(true);
  expect(requestClientJson).toHaveBeenCalledTimes(2);

  await act(async () => { await jest.advanceTimersByTimeAsync(59_999); });
  expect(requestClientJson).toHaveBeenCalledTimes(2);
  await act(async () => tree.unmount());
});

it("ignores an old user's late poll after an account switch and starts the next user at cursor zero", async () => {
  const pending = deferred<unknown>();
  const userB = { ...userA, user: { user_id: "u2", name: "Next worker" }, access: { ...userA.access, user: { user_id: "u2", name: "Next worker" } } };
  (loadBrowserSession as jest.Mock).mockResolvedValueOnce(sessionA).mockResolvedValueOnce({ authenticated: true, bootstrap: userB });
  (requestClientJson as jest.Mock).mockImplementation((path: string) => {
    if (path === userA.links.logout) return Promise.resolve({});
    if (path.includes("/me/notifications")) {
      if ((requestClientJson as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/me/notifications")).length === 1) return pending.promise;
      return Promise.resolve(emptyPage(0));
    }
    return Promise.resolve({});
  });
  const tree = await mountProvider();
  expect((requestClientJson as jest.Mock).mock.calls[0][0]).toBe("/api/v1/me/notifications?after=0");

  await act(async () => { await state.reload(); });
  await settle();
  expect(state.bootstrap?.user.user_id).toBe("u2");
  const generationAfterSwitch = state.notificationGeneration;
  expect((requestClientJson as jest.Mock).mock.calls.filter(([url]) => String(url).includes("/me/notifications")).map(([url]) => url)).toEqual([
    "/api/v1/me/notifications?after=0",
    "/api/v1/me/notifications?after=0",
  ]);

  await act(async () => { pending.resolve({ notifications: [notification(50)], next_cursor: 50 }); });
  await settle();
  expect(state.authenticated).toBe(true);
  expect(state.bootstrap?.user.user_id).toBe("u2");
  expect(state.notificationGeneration).toBe(generationAfterSwitch);
  await act(async () => tree.unmount());
});

describe("idle sign-out and the background label", () => {
  const MIN = 60_000;
  let assign: jest.Mock;
  beforeEach(() => {
    assign = jest.fn();
    Object.defineProperty(window, "location", { configurable: true, value: { assign } });
  });
  const dialogs = (tree: ReturnType<typeof create>) => tree.root.findAllByType(ConfirmDialog);

  it("labels the notification poll and the focus reload as background", async () => {
    const tree = await mountProvider();
    expect((requestClientJson as jest.Mock).mock.calls[0][1]).toEqual({ background: true });
    (loadBrowserSession as jest.Mock).mockClear();
    emitVisibilityChange();
    await settle();
    expect(loadBrowserSession).toHaveBeenCalledWith(true);
    await act(async () => { await state.reload(); });
    expect(loadBrowserSession).toHaveBeenLastCalledWith(false);
    await act(async () => tree.unmount());
  });

  it("warns at 28 minutes and signs out at 30", async () => {
    const tree = await mountProvider();
    await act(async () => { await jest.advanceTimersByTimeAsync(27 * MIN); });
    expect(dialogs(tree)).toHaveLength(0);
    await act(async () => { await jest.advanceTimersByTimeAsync(1 * MIN); });
    expect(dialogs(tree)).toHaveLength(1);
    expect(assign).not.toHaveBeenCalled();
    await act(async () => { await jest.advanceTimersByTimeAsync(2 * MIN); });
    expect(dialogs(tree)).toHaveLength(0);
    expect(assign).toHaveBeenCalledWith("/vaauth/valogin?reason=idle");
    await act(async () => tree.unmount());
  });

  it("user input restarts the count and sends a keep-alive at most every 30 seconds", async () => {
    const tree = await mountProvider();
    const input = () => { for (const handler of windowHandlers.keydown ?? []) (handler as (e: unknown) => void)({ isTrusted: true }); };
    const pings = () => (requestClientJson as jest.Mock).mock.calls.filter(([path, options]) => path === "/api/v1/me/access" && !options).length;
    await act(async () => { await jest.advanceTimersByTimeAsync(20 * MIN); });
    input(); input();
    expect(pings()).toBe(1);
    await act(async () => { await jest.advanceTimersByTimeAsync(27 * MIN); });
    expect(dialogs(tree)).toHaveLength(0);
    await act(async () => tree.unmount());
  });

  it("Stay signed in (also Escape and the default button) restarts the count with one ordinary request", async () => {
    const tree = await mountProvider();
    await act(async () => { await jest.advanceTimersByTimeAsync(28 * MIN); });
    const dialog = dialogs(tree)[0];
    await act(async () => { dialog.props.onCancel(); });
    expect(dialogs(tree)).toHaveLength(0);
    const last = (requestClientJson as jest.Mock).mock.calls.at(-1)!;
    expect(last[0]).toBe("/api/v1/me/access");
    expect(last[1]).toBeUndefined();
    await act(async () => { await jest.advanceTimersByTimeAsync(29 * MIN); });
    expect(assign).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("a session_idle refusal from any request goes to sign-in with the reason", async () => {
    const tree = await mountProvider();
    // The mocked removeEventListener keeps stale handlers; the newest one is the live one.
    await act(async () => { windowHandlers["digitva-session-idle"].at(-1)!(); });
    await settle();
    expect(assign).toHaveBeenCalledWith("/vaauth/valogin?reason=idle");
    await act(async () => tree.unmount());
  });

  it("ignores script-dispatched input", async () => {
    const tree = await mountProvider();
    await act(async () => { await jest.advanceTimersByTimeAsync(20 * MIN); });
    for (const handler of windowHandlers.keydown ?? []) (handler as (e: unknown) => void)({ isTrusted: false });
    await act(async () => { await jest.advanceTimersByTimeAsync(10 * MIN); });
    expect(assign).toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("sign-out waits for a pending save and clears the recalled details", async () => {
    const store = new Map<string, string>([["digitva.interviewerRecall.name", "x"], ["other", "y"]]);
    Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
      get length() { return store.size; },
      key: (index: number) => [...store.keys()][index] ?? null,
      removeItem: (key: string) => { store.delete(key); },
      getItem: jest.fn(), setItem: jest.fn(), clear: jest.fn(),
    } });
    const tree = await mountProvider();
    const save = deferred<void>();
    state.onBeforeLock(() => save.promise);
    await act(async () => { await jest.advanceTimersByTimeAsync(30 * MIN); });
    expect(assign).not.toHaveBeenCalled();
    await act(async () => { save.resolve(); await jest.advanceTimersByTimeAsync(10); });
    expect(assign).toHaveBeenCalledWith("/vaauth/valogin?reason=idle");
    expect([...store.keys()]).toEqual(["other"]);
    await act(async () => tree.unmount());
  });

  it("sign-out still happens when the save never finishes", async () => {
    const tree = await mountProvider();
    state.onBeforeLock(() => new Promise<void>(() => undefined));
    await act(async () => { await jest.advanceTimersByTimeAsync(30 * MIN + 6000); });
    expect(assign).toHaveBeenCalled();
    await act(async () => tree.unmount());
  });
});
