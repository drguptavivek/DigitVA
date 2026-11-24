/** Pins the case screen's queued actions, discard, call, directions and share (bead r8nh.26). */
import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockDb = {};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn();
const mockLockNow = jest.fn();
const mockAccounts = [mockAccount];
let mockParams: { userId: string; projectId?: string; deathId?: string; clientDeathId?: string } = {
  userId: "u1",
  projectId: "P1",
  deathId: "d1",
};
const mockDetail = {
  death_id: "d1",
  project_id: "P1",
  unique_id: "VA-001",
  site_id: "S1",
  org_unit_id: null,
  unit_name: "Block A",
  state: "registered",
  source: "reported",
  details_pending: false,
  pending_flag: false,
  registered_by_me: false,
  started_by_me: false,
  my_draft_id: null,
  va_sid: null,
  created_at: "",
  updated_at: "",
  next_visit_at: null,
  last_contact_at: null,
  deceased: {
    name: "Asha Devi",
    sex: "female",
    age_years: 72,
    date_of_birth: null,
    date_of_birth_partial: null,
    date_of_death: "2026-09-30",
    place_of_death: "Home",
  },
  household_address: {
    address: "House 4",
    house_street: "East Road",
    village_ward: "Ward 2",
    landmark: "Temple",
  },
  informant: {
    name: "Sita Devi",
    phone: "+919876543210",
    phone_2: "9876543211",
  },
  remarks: "Ask at the east gate",
  prefill: {},
  links: { self: "", attempts: "", visit: "" },
};

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (callback: () => undefined | (() => void)) => {
    const R = jest.requireActual("react") as typeof React;
    R.useEffect(callback, [callback]);
  },
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: mockAccounts,
    reload: mockReload,
    lockNow: mockLockNow,
  }),
}));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => true,
  openInterviewerDb: jest.fn(async () => mockDb),
}));
jest.mock("../src/drafts", () => ({
  draftForCase: jest.fn(async () => null),
  listDrafts: jest.fn(async () => []),
  listCases: jest.fn(async () => [mockDetail]),
  listActions: jest.fn(async () => []),
  draftIds: jest.fn(async () => []),
  getMeta: jest.fn(async () => null),
}));
jest.mock("../src/cases", () => {
  const actual = jest.requireActual("../src/cases") as Record<string, unknown>;
  return {
    ...actual,
    getCase: jest.fn(async () => mockDetail),
    listCases: jest.fn(async () => [mockDetail]),
    listRegistrations: jest.fn(async () => []),
    listActions: jest.fn(async () => []),
    getRegistration: jest.fn(async () => undefined),
    queueAction: jest.fn(async () => undefined),
    deleteAction: jest.fn(),
    discardRegistration: jest.fn(),
    visitAt: (value: string) => `${value}T09:00:00.000Z`,
  };
});
jest.mock("../src/unsentWork", () => ({
  sendRefusal: jest.fn(async () => undefined),
}));
jest.mock("../src/sync", () => ({
  fetchCaseDetail: jest.fn(async () => mockDetail),
  getCachedReferenceData: jest.fn(async () => ({
    bootstrap: { user: mockAccount, instrument_version: "v1", projects: [] },
    projects: [],
  })),
  refreshReferenceData: jest.fn(async () => undefined),
}));
jest.mock("../src/revisions", () => ({ fetchSubmittedRevisions: jest.fn().mockResolvedValue([]) }));
jest.mock("../src/draftSync", () => ({
  reconcileCaseDraft: jest.fn(async (_user: string, _db: unknown, _detail: unknown, local: unknown) => ({
    draft: local,
    conflict: false,
    message: null,
    imported: false,
  })),
}));
jest.mock("../src/ui", () => {
  const R = jest.requireActual("react") as any;
  return {
    Button: ({
      label,
      onPress,
      disabled,
    }: {
      label: string;
      onPress?: () => void;
      disabled?: boolean;
    }) =>
      R.createElement(
        "button",
        { "data-label": label, disabled, onClick: onPress },
        label,
      ),
    Row: ({ children }: { children: ReactNode }) =>
      R.createElement("div", null, children),
    Screen: ({ children }: { children: ReactNode }) =>
      R.createElement("main", null, children),
    errorText: (error: unknown) => String(error),
    stateLabel: (state: string) => state,
    ChoiceRow: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
      (jest.requireActual("react") as typeof import("react")).createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
    Card: ({ children }: { children: React.ReactNode }) => (jest.requireActual("react") as typeof import("react")).createElement("div", null, children),
    Separator: () => null,
    // The petrol notice as a plain text (an alert for error and warning, as the real one), so the message assertions keep reading its words.
    Notice: ({ children, testID, tone }: { children: React.ReactNode; testID?: string; tone?: string }) =>
      (jest.requireActual("react") as typeof import("react")).createElement((require("react-native") as typeof import("react-native")).Text, { accessibilityRole: tone === "error" || tone === "warning" ? "alert" : undefined, testID }, children),
    useUiStyles: () => ({
      text: {},
      muted: {},
      headline: {},
      error: {},
      card: {},
      input: {},
    }),
  };
});
jest.mock("../src/i18n", () => ({
  uiLanguageTag: () => "en",
  t: (key: string, vars?: Record<string, unknown>) =>
    `${key}${vars?.date ? ` ${String(vars.date)}` : ""}${vars?.time ? ` @${String(vars.time)}` : ""}`,
  uiLocale: () => "en",
}));

import Case from "../src/nativeRoutes/case";
import { formatDisplayTimestamp } from "../src/ui/CaseCard";
import { ShellContext } from "../src/nativeShell/shellContext";
import { Linking } from "react-native";

const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

beforeEach(() => {
  jest.clearAllMocks();
  jest.spyOn(Linking, "openURL").mockResolvedValue(true);
  mockParams = { userId: "u1", projectId: "P1", deathId: "d1" };
  (
    jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock
  ).mockResolvedValue(mockDetail);
});


import { Platform, Share, TextInput } from "react-native";

const cases = () => jest.requireMock("../src/cases") as Record<string, jest.Mock>;
const click = (tree: ReturnType<typeof create>, label: string) =>
  act(async () => tree.root.findByProps({ "data-label": label }).props.onClick());
const isoDay = (offsetDays: number) => new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);

async function open(): Promise<ReturnType<typeof create>> {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Case />); });
  await settle();
  await settle();
  return tree;
}
const typeDate = (tree: ReturnType<typeof create>, value: string) =>
  act(async () => tree.root.findByType(TextInput).props.onChangeText(value));
const shown = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());

describe("case actions", () => {
  it("queues a visit with its date on the opened case", async () => {
    const tree = await open();
    await click(tree, "setVisit");
    const day = isoDay(3);
    await typeDate(tree, day);
    await click(tree, "save");
    expect(cases().queueAction).toHaveBeenCalledWith(mockDb, expect.objectContaining({
      project_id: "P1", death_id: "d1", client_death_id: null, kind: "visit", body: { next_visit_at: `${day}T09:00:00.000Z` },
    }));
    expect(shown(tree)).toContain("queued");
    await act(async () => tree.unmount());
  });

  it.each([
    ["no date for a visit", "", "errVisitDate"],
    ["a date more than a day in the past", isoDay(-3), "errVisitDate"],
    ["a date more than 366 days ahead", isoDay(400), "errVisitDate"],
  ])("refuses a visit with %s and queues nothing", async (_name, value, message) => {
    const tree = await open();
    await click(tree, "setVisit");
    await typeDate(tree, value);
    await click(tree, "save");
    expect(cases().queueAction).not.toHaveBeenCalled();
    expect(shown(tree)).toContain(message);
    await act(async () => tree.unmount());
  });

  it("asks for an outcome before queueing a contact attempt", async () => {
    const tree = await open();
    await click(tree, "logAttempt");
    await click(tree, "save");
    expect(cases().queueAction).not.toHaveBeenCalled();
    expect(shown(tree)).toContain("errRequired");
    await act(async () => tree.unmount());
  });

  it("queues an attempt with its outcome and next visit, but drops the date for a refusal", async () => {
    const tree = await open();
    await click(tree, "logAttempt");
    await click(tree, "outcome_reached");
    const day = isoDay(2);
    await typeDate(tree, day);
    await click(tree, "save");
    expect(cases().queueAction).toHaveBeenLastCalledWith(mockDb, expect.objectContaining({
      kind: "attempt", body: { outcome: "reached", next_visit_at: `${day}T09:00:00.000Z` },
    }));
    await click(tree, "logAttempt");
    await click(tree, "outcome_reached");
    await typeDate(tree, day);
    await click(tree, "outcome_refused");
    await click(tree, "save");
    expect(cases().queueAction).toHaveBeenLastCalledWith(mockDb, expect.objectContaining({ kind: "attempt", body: { outcome: "refused" } }));
    await act(async () => tree.unmount());
  });

  it("discards a queued action by its client id and reloads the list", async () => {
    cases().listActions.mockResolvedValue([
      { client_id: "a1", project_id: "P1", kind: "attempt", death_id: "d1", client_death_id: null, body: { outcome: "moved" }, state: "needs_edit", created_at: "" },
      { client_id: "a2", project_id: "P1", kind: "visit", death_id: "other", client_death_id: null, body: {}, state: "needs_edit", created_at: "" },
    ]);
    const tree = await open();
    // Only this case's queued actions are listed.
    expect(tree.root.findAllByProps({ "data-label": "discard" })).toHaveLength(1);
    cases().listActions.mockClear();
    await click(tree, "discard");
    expect(cases().deleteAction).toHaveBeenCalledWith(mockDb, "a1");
    expect(cases().listActions).toHaveBeenCalled();
    cases().listActions.mockResolvedValue([]);
    await act(async () => tree.unmount());
  });

  it("discards a refused registration and goes back", async () => {
    mockParams = { userId: "u1", projectId: "P1", clientDeathId: "c1" };
    cases().getRegistration.mockResolvedValue({
      client_death_id: "c1", project_id: "P1", site_id: "S1", org_unit_id: null, fields: { deceased_name: "Local" }, state: "needs_edit", created_at: "",
    });
    const tree = await open();
    await click(tree, "discard");
    expect(cases().discardRegistration).toHaveBeenCalledWith(mockDb, "c1");
    expect(mockRouter.back).toHaveBeenCalledTimes(1);
    cases().getRegistration.mockResolvedValue(undefined);
    await act(async () => tree.unmount());
  });

  it("shows a failed call as the message and offers the button again", async () => {
    (Linking.openURL as jest.Mock).mockRejectedValueOnce(new Error("no dialer"));
    const tree = await open();
    await act(async () => tree.root.findAllByProps({ "data-label": "callInformant" })[0].props.onClick());
    expect(shown(tree)).toContain("Error: no dialer");
    expect(tree.root.findAllByProps({ "data-label": "callInformant" })[0].props.disabled).toBe(false);
    await act(async () => tree.unmount());
  });

  describe("with a recorded location", () => {
    const located = { ...mockDetail, household_address: { ...mockDetail.household_address, latitude: 12.5, longitude: 77.25, accuracy_m: 8.4 } };
    const original = Platform.OS;
    beforeEach(() => {
      (jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock).mockResolvedValue(located);
    });
    afterEach(() => { Platform.OS = original; });

    it("shares the map link", async () => {
      const share = jest.spyOn(Share, "share").mockResolvedValue({ action: "sharedAction" } as never);
      const tree = await open();
      await click(tree, "shareLocation");
      expect(share).toHaveBeenCalledWith({ message: "https://www.google.com/maps/dir/?api=1&destination=12.5,77.25" });
      await act(async () => tree.unmount());
    });

    it("opens directions on Android, trying the next link when the first fails", async () => {
      Platform.OS = "android";
      (Linking.openURL as jest.Mock).mockRejectedValueOnce(new Error("no maps"));
      const tree = await open();
      await click(tree, "directions");
      expect((Linking.openURL as jest.Mock).mock.calls.map((c) => c[0])).toEqual(["google.navigation:q=12.5,77.25", "geo:12.5,77.25?q=12.5,77.25"]);
      expect(shown(tree)).not.toContain("no maps");
      await act(async () => tree.unmount());
    });

    it("says why when every directions link fails", async () => {
      Platform.OS = "android";
      (Linking.openURL as jest.Mock).mockRejectedValue(new Error("no maps"));
      const tree = await open();
      await click(tree, "directions");
      expect(shown(tree)).toContain("Error: no maps");
      await act(async () => tree.unmount());
    });
  });
});
