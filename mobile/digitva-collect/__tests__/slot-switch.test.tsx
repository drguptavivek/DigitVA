/**
 * Switching between the Active and Demo enrolments (docs/policy/public-demo.md
 * section 10.1): open work is saved and every store locked first, then the
 * other slot is chosen and both slots' accounts are kept. A slot not enrolled
 * yet opens its enrolment screen and stays unchosen; an empty Demo slot is
 * left for Active. A poll for a user the chosen slot no longer serves is
 * skipped quietly.
 */
import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockSecure = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  WHEN_UNLOCKED_THIS_DEVICE_ONLY: 0,
  getItemAsync: jest.fn(async (key: string) => mockSecure.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => {
    if (key === "active_slot") mockEvents.push(`slot:${value}`);
    mockSecure.set(key, value);
  }),
  deleteItemAsync: jest.fn(async (key: string) => {
    if (key === "active_slot") mockEvents.push("slot:active");
    mockSecure.delete(key);
  }),
}));
const mockRouter = { replace: jest.fn(), push: jest.fn() };
jest.mock("expo-router", () => ({ useRouter: () => mockRouter }));
jest.mock("expo-localization", () => ({ getLocales: () => [{ languageCode: "en" }] }));
let mockUnlocked = false;
const mockEvents: string[] = [];
const mockLockAll = jest.fn(async () => {
  mockEvents.push("lockAll");
  mockUnlocked = false;
});
jest.mock("../src/interviewerDb", () => ({
  anyUnlocked: () => mockUnlocked,
  isUnlocked: () => mockUnlocked,
  lockAll: () => mockLockAll(),
  deleteInterviewerDb: jest.fn(),
}));
jest.mock("../src/autoLock", () => ({
  createAutoLock: () => ({ activity: jest.fn(), appStateChanged: jest.fn(), stop: jest.fn() }),
}));
jest.mock("../src/i18n", () => ({ setUiLocale: () => "en", t: (key: string) => key }));

import { AppStateProvider, useAppState } from "../src/AppState";
import * as auth from "../src/auth";
import DemoBadge from "../src/DemoBadge";
import { DEMO_SERVER } from "../src/enrolment";

const LIVE = "https://digitva.causeofdeathindia.com";
const liveAccounts = JSON.stringify([{ user_id: "live-user", name: "Asha", server: LIVE }]);
const demoAccounts = JSON.stringify([{ user_id: "demo-user", name: "demo.asha", server: DEMO_SERVER }]);

let state!: ReturnType<typeof useAppState>;
function Probe() {
  state = useAppState();
  return (
    <React.Fragment>
      {JSON.stringify({ slot: state.slot, accounts: state.accounts.map((a) => a.user_id) })}
      <DemoBadge server={state.device?.server} />
    </React.Fragment>
  );
}

async function render(children?: React.ReactNode): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<AppStateProvider><Probe />{children}</AppStateProvider>);
  });
  return tree;
}
const out = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => {
  mockSecure.clear();
  mockEvents.length = 0;
  mockUnlocked = false;
  jest.clearAllMocks();
  mockSecure.set("device", JSON.stringify({ device_id: "live-1", server: LIVE, project_id: "P", project_name: "Live" }));
  mockSecure.set("accounts", liveAccounts);
  // No network: the startup refresh stops at its offline check.
  globalThis.fetch = jest.fn(async () => { throw new TypeError("offline"); }) as typeof fetch;
});

it("hides an account signed in on another server and keeps its entry on the phone", async () => {
  const mixed = JSON.stringify([
    { user_id: "live-user", name: "Asha", server: LIVE },
    { user_id: "old-user", name: "Old", server: "https://old.causeofdeathindia.com" },
    { user_id: "legacy-user", name: "Legacy" },
  ]);
  mockSecure.set("accounts", mixed);
  const tree = await render();
  expect(out(tree)).toContain('\\"accounts\\":[\\"live-user\\",\\"legacy-user\\"]');
  expect(out(tree)).not.toContain("old-user");
  // Hidden, not removed: its entry (and so its encrypted store) stays. The legacy account is bound to this
  // device's server on the first reload, so a later enrolment elsewhere hides it too.
  expect(JSON.parse(mockSecure.get("accounts")!)).toEqual([
    { user_id: "live-user", name: "Asha", server: LIVE },
    { user_id: "old-user", name: "Old", server: "https://old.causeofdeathindia.com" },
    { user_id: "legacy-user", name: "Legacy", server: LIVE },
  ]);
  const writes = (jest.requireMock("expo-secure-store").setItemAsync as jest.Mock).mock.calls.filter(([key]) => key === "accounts");
  expect(writes).toHaveLength(1);

  // The phone is enrolled on another server: every account of the old one, the legacy one included, is hidden.
  mockSecure.set("device", JSON.stringify({ device_id: "new-1", server: "https://new.causeofdeathindia.com", project_id: "N", project_name: "New" }));
  await act(async () => {
    await state.reload();
  });
  expect(out(tree)).toContain('\\"accounts\\":[]');
  expect(JSON.parse(mockSecure.get("accounts")!).map((a: { user_id: string }) => a.user_id)).toEqual(["live-user", "old-user", "legacy-user"]);
  await act(async () => tree.unmount());
});

it("keeps standalone unavailable until both slots are read, then recomputes on reload and other-slot logout", async () => {
  mockSecure.set("accounts", "[]");
  let finish!: (value: boolean) => void;
  const check = jest.spyOn(auth, "standaloneModeAvailable").mockImplementationOnce(() =>
    new Promise<boolean>((resolve) => { finish = resolve; }),
  );
  const tree = await render();
  expect(state.ready).toBe(false);
  expect(state.standaloneAvailable).toBe(false);
  await act(async () => finish(true));
  expect(state.ready).toBe(true);
  expect(state.standaloneAvailable).toBe(true);
  check.mockRestore();

  mockSecure.set("demo.accounts", demoAccounts);
  await act(async () => state.reload());
  expect(state.standaloneAvailable).toBe(false);
  expect(state.slot).toBe("active");
  expect(state.accounts).toEqual([]);

  await act(async () => { await auth.signOut("demo-user"); });
  expect(state.standaloneAvailable).toBe(true);
  expect(state.slot).toBe("active");
  expect(state.accounts).toEqual([]);

  mockSecure.set("demo.accounts", "not-json");
  await act(async () => {
    await expect(state.reload()).rejects.toBeInstanceOf(auth.AccountStoreCollisionError);
  });
  expect(state.standaloneAvailable).toBe(false);
  await act(async () => tree.unmount());
});

it("fails closed during a failed reload instead of retaining earlier standalone availability", async () => {
  mockSecure.set("accounts", "[]");
  const tree = await render();
  expect(state.standaloneAvailable).toBe(true);
  const read = jest.spyOn(auth, "loadActiveSlot").mockRejectedValueOnce(new Error("storage failed"));
  await act(async () => {
    await expect(state.reload()).rejects.toThrow("storage failed");
  });
  expect(state.standaloneAvailable).toBe(false);
  read.mockRestore();
  await act(async () => tree.unmount());
});

it("ignores an older eligibility read after a newer account reload refused standalone", async () => {
  mockSecure.set("accounts", "[]");
  const tree = await render();
  expect(state.standaloneAvailable).toBe(true);
  let finish!: (value: boolean) => void;
  const check = jest.spyOn(auth, "standaloneModeAvailable").mockImplementationOnce(() =>
    new Promise<boolean>((resolve) => { finish = resolve; }),
  );
  let older!: Promise<void>;
  await act(async () => {
    older = state.reload();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(state.standaloneAvailable).toBe(true);
  mockSecure.set("demo.accounts", demoAccounts);
  await act(async () => state.reload());
  expect(state.standaloneAvailable).toBe(false);
  await act(async () => {
    finish(true);
    await older;
  });
  expect(state.standaloneAvailable).toBe(false);
  check.mockRestore();
  await act(async () => tree.unmount());
});

it("keeps an eligible standalone form mounted while an unchanged reload is pending", async () => {
  mockSecure.set("accounts", JSON.stringify([{ user_id: "standalone-local", name: "Local", standalone: true }]));
  const unmount = jest.fn();
  function Form() {
    React.useEffect(() => unmount, []);
    return <>standalone-form</>;
  }
  function StandaloneRoute() {
    const app = useAppState();
    return app.ready && app.standaloneAvailable ? <Form /> : null;
  }
  const tree = await render(<StandaloneRoute />);
  expect(out(tree)).toContain("standalone-form");
  expect(state.standaloneAvailable).toBe(true);
  let finish!: (value: boolean) => void;
  const check = jest.spyOn(auth, "standaloneModeAvailable").mockImplementationOnce(() =>
    new Promise<boolean>((resolve) => { finish = resolve; }),
  );
  let pending!: Promise<void>;
  await act(async () => {
    pending = state.reload();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(state.standaloneAvailable).toBe(true);
  expect(out(tree)).toContain("standalone-form");
  expect(unmount).not.toHaveBeenCalled();
  await act(async () => {
    finish(true);
    await pending;
  });
  expect(state.standaloneAvailable).toBe(true);
  expect(unmount).not.toHaveBeenCalled();
  check.mockRestore();
  await act(async () => tree.unmount());
});

it("publishes only the newest slot, device and accounts when older account storage finishes last", async () => {
  const tree = await render();
  let finish!: (value: auth.Account[]) => void;
  const read = jest.spyOn(auth, "loadAccounts").mockImplementationOnce(() =>
    new Promise<auth.Account[]>((resolve) => { finish = resolve; }),
  );
  let older!: Promise<void>;
  await act(async () => {
    older = state.reload();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  const demoDevice = { device_id: "demo-new", server: DEMO_SERVER, project_id: "D", project_name: "Demo" };
  mockSecure.set("active_slot", "demo");
  mockSecure.set("demo.device", JSON.stringify(demoDevice));
  mockSecure.set("demo.accounts", demoAccounts);
  await act(async () => state.reload());
  const newest = { slot: state.slot, device: state.device, accounts: state.accounts, available: state.standaloneAvailable };
  expect(newest).toEqual({ slot: "demo", device: demoDevice, accounts: JSON.parse(demoAccounts), available: false });
  await act(async () => {
    finish([{ user_id: "old-active", name: "Old", server: LIVE }]);
    await older;
  });
  expect({ slot: state.slot, device: state.device, accounts: state.accounts, available: state.standaloneAvailable }).toEqual(newest);
  read.mockRestore();
  await act(async () => tree.unmount());
});

it("does not mark startup ready when an older read finishes before the newest reload", async () => {
  let finishOlder!: (value: boolean) => void;
  let finishNewer!: (value: boolean) => void;
  const check = jest.spyOn(auth, "standaloneModeAvailable")
    .mockImplementationOnce(() => new Promise<boolean>((resolve) => { finishOlder = resolve; }))
    .mockImplementationOnce(() => new Promise<boolean>((resolve) => { finishNewer = resolve; }));
  const tree = await render();
  let newer!: Promise<void>;
  await act(async () => {
    newer = state.reload();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await act(async () => finishOlder(true));
  expect(state.ready).toBe(false);
  expect(state.standaloneAvailable).toBe(false);
  expect(state.device).toBeUndefined();
  expect(state.accounts).toEqual([]);
  await act(async () => {
    finishNewer(false);
    await newer;
  });
  expect(state.ready).toBe(true);
  expect(state.accounts).toEqual(JSON.parse(liveAccounts));
  check.mockRestore();
  await act(async () => tree.unmount());
});

it("keeps a newer valid snapshot when an obsolete reload fails", async () => {
  mockSecure.set("accounts", "[]");
  const tree = await render();
  let fail!: (error: Error) => void;
  const check = jest.spyOn(auth, "standaloneModeAvailable").mockImplementationOnce(() =>
    new Promise<boolean>((_resolve, reject) => { fail = reject; }),
  );
  let older!: Promise<void>;
  await act(async () => {
    older = state.reload();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  await act(async () => state.reload());
  expect(state.standaloneAvailable).toBe(true);
  await act(async () => {
    fail(new Error("obsolete storage failure"));
    await older;
  });
  expect(state.ready).toBe(true);
  expect(state.standaloneAvailable).toBe(true);
  expect(state.backgroundError).toBeUndefined();
  check.mockRestore();
  await act(async () => tree.unmount());
});

it("keeps startup unavailable and reports a failed initial read", async () => {
  const read = jest.spyOn(auth, "loadActiveSlot").mockRejectedValueOnce(new Error("storage failed"));
  const tree = await render();
  expect(state.ready).toBe(false);
  expect(state.standaloneAvailable).toBe(false);
  expect(state.backgroundError).toBeDefined();
  expect(state.accounts).toEqual([]);
  read.mockRestore();
  await act(async () => tree.unmount());
});

it("saves open work, locks every store, then shows the demo slot with both slots' accounts kept", async () => {
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO_SERVER, project_id: "D", project_name: "Demo" }));
  mockSecure.set("demo.accounts", demoAccounts);
  const tree = await render();
  expect(out(tree)).toContain('\\"slot\\":\\"active\\",\\"accounts\\":[\\"live-user\\"]');

  mockUnlocked = true;
  act(() => {
    state.onBeforeLock(async () => void mockEvents.push("flush"));
  });
  let switched: boolean | undefined;
  await act(async () => {
    switched = await state.switchSlot!("demo");
  });

  expect(switched).toBe(true);
  // The slot is written only after open work is saved and every store is closed.
  expect(mockEvents).toEqual(["flush", "lockAll", "slot:demo"]);
  expect(mockSecure.get("active_slot")).toBe("demo");
  expect(mockSecure.get("accounts")).toBe(liveAccounts);
  expect(mockSecure.get("demo.accounts")).toBe(demoAccounts);
  expect(mockRouter.replace).toHaveBeenLastCalledWith("/");
  expect(mockRouter.push).not.toHaveBeenCalled();
  expect(out(tree)).toContain('\\"slot\\":\\"demo\\",\\"accounts\\":[\\"demo-user\\"]');
  // The demo slot's device is on the demo server, so the badge shows.
  expect(out(tree)).toContain("demoHeaderBadge");

  await act(async () => {
    await state.switchSlot!("active");
  });
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(out(tree)).toContain('\\"slot\\":\\"active\\",\\"accounts\\":[\\"live-user\\"]');
  // Active shows no DEMO badge.
  expect(out(tree)).not.toContain("demoHeaderBadge");
});

it("opens Try the demo when the phone has no demo enrolment, keeping the current slot", async () => {
  const tree = await render();
  await act(async () => {
    await state.switchSlot!("demo");
  });
  expect(mockRouter.push).toHaveBeenCalledWith("/demo");
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(out(tree)).toContain('\\"slot\\":\\"active\\"');
});

it("opens QR enrolment when switching to Active without a live enrolment", async () => {
  mockSecure.clear();
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO_SERVER, project_id: "D", project_name: "Demo" }));
  mockSecure.set("demo.accounts", demoAccounts);
  mockSecure.set("active_slot", "demo");
  const tree = await render();
  expect(out(tree)).toContain('\\"slot\\":\\"demo\\"');
  await act(async () => {
    await state.switchSlot!("active");
  });
  expect(mockRouter.push).toHaveBeenCalledWith("/enrol");
  expect(mockSecure.get("active_slot")).toBe("demo");
});

it("changes nothing when saving open work fails", async () => {
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO_SERVER, project_id: "D", project_name: "Demo" }));
  await render();
  mockUnlocked = true;
  act(() => {
    state.onBeforeLock(async () => { throw new Error("save failed"); });
  });
  let switched: boolean | undefined;
  await act(async () => {
    switched = await state.switchSlot!("demo");
  });
  expect(switched).toBe(false);
  expect(mockLockAll).not.toHaveBeenCalled();
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(mockEvents).toEqual([]);
});

it("changes nothing when closing a store fails", async () => {
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO_SERVER, project_id: "D", project_name: "Demo" }));
  await render();
  mockUnlocked = true;
  mockLockAll.mockImplementationOnce(async () => {
    mockEvents.push("lockAll");
    throw new Error("close failed");
  });
  let switched: boolean | undefined;
  await act(async () => {
    switched = await state.switchSlot!("demo");
  });
  expect(switched).toBe(false);
  expect(mockEvents).toEqual(["lockAll"]);
  expect(mockSecure.has("active_slot")).toBe(false);
});

it("leaves an empty Demo slot for Active even when Active is not enrolled either", async () => {
  mockSecure.clear();
  mockSecure.set("active_slot", "demo");
  const tree = await render();
  await act(async () => {
    await state.switchSlot!("active");
  });
  expect(mockSecure.has("active_slot")).toBe(false);
  expect(mockRouter.push).not.toHaveBeenCalled();
  expect(mockRouter.replace).toHaveBeenLastCalledWith("/");
  expect(out(tree)).toContain('\\"slot\\":\\"active\\"');
});

it("skips a poll for a user the chosen slot no longer serves, without a banner", async () => {
  const spy = jest.spyOn(auth, "refreshAccessSummary");
  mockSecure.set("tokens.live-user", JSON.stringify({ access_token: "a", access_expires_at: "", refresh_token: "r", refresh_expires_at: "" }));
  await render();
  // A switch landed (another path) after Home last read the live accounts.
  mockSecure.set("demo.device", JSON.stringify({ device_id: "demo-1", server: DEMO_SERVER, project_id: "D", project_name: "Demo" }));
  mockSecure.set("demo.accounts", demoAccounts);
  mockSecure.set("active_slot", "demo");
  spy.mockClear();
  (globalThis.fetch as jest.Mock).mockClear();

  await act(async () => {
    state.unlocked();
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  // The refusal happened (the poll reached the live user) and was skipped.
  expect(spy).toHaveBeenCalledWith("live-user");
  await expect(spy.mock.results[0].value).rejects.toBeInstanceOf(auth.NotInSlotError);
  expect(globalThis.fetch).not.toHaveBeenCalled();
  expect(state.backgroundError).toBeUndefined();
  expect(JSON.parse(mockSecure.get("accounts")!)[0].needs_sign_in).toBeUndefined();
  spy.mockRestore();
});
