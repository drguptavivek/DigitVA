import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockDb = {};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn();
const mockLockNow = jest.fn();
const mockAccounts = [mockAccount];
let mockParams: { userId: string; projectId?: string; deathId?: string } = {
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
jest.mock("../src/sync", () => ({
  fetchCaseDetail: jest.fn(async () => mockDetail),
  getCachedReferenceData: jest.fn(async () => ({
    bootstrap: { user: mockAccount, instrument_version: "v1", projects: [] },
    projects: [],
  })),
  refreshReferenceData: jest.fn(async () => undefined),
}));
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
  t: (key: string, vars?: Record<string, unknown>) =>
    `${key}${vars?.date ? ` ${String(vars.date)}` : ""}`,
  uiLocale: () => "en",
}));

import Case from "../src/nativeRoutes/case";
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

describe("native case detail workflow", () => {
  it("keeps contacts visible but offers no new interview when prefill is withheld", async () => {
    const { prefill: _prefill, ...heldCase } = mockDetail;
    (jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock).mockResolvedValue(heldCase);
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<Case />); });
    await settle();
    await settle();
    expect(tree!.root.findByProps({ children: "+919876543210" })).toBeDefined();
    expect(tree!.root.findAllByProps({ "data-label": "startInterview" })).toHaveLength(0);
    await act(async () => tree!.unmount());
  });

  it("keeps parallel interview start available and shows the stale warning", async () => {
    const startedAt = "2026-01-02T03:04:05.000Z";
    (
      jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock
    ).mockResolvedValue({
      ...mockDetail,
      state: "in_progress",
      other_draft_active: true,
      other_draft_started_at: startedAt,
      prefill: {},
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(
      `otherDraftActiveAt ${new Date(startedAt).toLocaleString()}`,
    );
    expect(rendered).toContain("otherDraftSyncNotice");
    const start = tree!.root.findByProps({ "data-label": "startInterview" });
    expect(start.props.disabled).toBe(false);
    await act(async () => start.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ deathId: "d1" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("resumes the imported server draft with its stable local id", async () => {
    const localId = "11111111-1111-4111-8111-111111111111";
    const localDraft = {
      id: localId,
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      death_id: "d1",
      unique_id: "VA-001",
      client_death_id: null,
    };
    (
      jest.requireMock("../src/draftSync").reconcileCaseDraft as jest.Mock
    ).mockResolvedValueOnce({
      draft: localDraft,
      conflict: false,
      message: null,
      imported: true,
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "resumeInterview" }).props.onClick(),
    );
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ draftId: localId, deathId: "d1" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("resumes a saved case draft from the authorized cache when offline", async () => {
    const localDraft = {
      id: "11111111-1111-4111-8111-111111111111",
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      death_id: "d1",
      unique_id: "VA-001",
      client_death_id: null,
    };
    (jest.requireMock("../src/drafts").draftForCase as jest.Mock).mockResolvedValueOnce(localDraft);
    (jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock).mockRejectedValueOnce(
      new TypeError("Network request failed"),
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    expect(tree!.root.findByProps({ "data-label": "resumeInterview" })).toBeDefined();
    expect(jest.requireMock("../src/cases").getCase).toHaveBeenCalledWith(mockDb, "d1");
    await act(async () => tree!.unmount());
  });

  it("keeps terminal cases unavailable for a new interview", async () => {
    (
      jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock
    ).mockResolvedValue({
      ...mockDetail,
      state: "cancelled",
      other_draft_active: true,
      prefill: {},
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    expect(
      tree!.root.findAllByProps({ "data-label": "startInterview" }),
    ).toHaveLength(0);
    expect(
      tree!.root.findByProps({ children: "caseActionsUnavailable" }),
    ).toBeDefined();
    await act(async () => tree!.unmount());
  });

  it("loads details by id, shows full authorized contacts and only calls manually", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    await settle();
    expect(
      jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock,
    ).toHaveBeenCalledWith("u1", mockDb, "d1");
    expect(
      tree!.root.findByProps({ children: "fieldInformantName: Sita Devi" }),
    ).toBeDefined();
    expect(tree!.root.findByProps({ children: "+919876543210" })).toBeDefined();
    expect(
      tree!.root.findAllByProps({ "data-label": "callInformant" }),
    ).toHaveLength(2);
    expect(Linking.openURL).not.toHaveBeenCalled();
    await act(async () =>
      tree!.root
        .findAllByProps({ "data-label": "callInformant" })[0]
        .props.onClick(),
    );
    expect(Linking.openURL).toHaveBeenCalledWith("tel:+919876543210");
    await act(async () => tree!.unmount());
  });

  it("queues contact attempts with the detail project and refetches by id", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "logAttempt" }).props.onClick(),
    );
    await act(async () =>
      tree!.root
        .findByProps({ "data-label": "outcome_reached" })
        .props.onClick(),
    );
    await act(async () =>
      tree!.root.findByProps({ "data-label": "save" }).props.onClick(),
    );
    expect(
      jest.requireMock("../src/cases").queueAction as jest.Mock,
    ).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({
        project_id: "P1",
        death_id: "d1",
        kind: "attempt",
      }),
    );
    expect(
      (jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock).mock.calls
        .length,
    ).toBeGreaterThan(1);
    await act(async () => tree!.unmount());
  });

  it("shows a missing detail without falling back to the cached list row", async () => {
    (
      jest.requireMock("../src/sync").fetchCaseDetail as jest.Mock
    ).mockResolvedValueOnce(undefined);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Case />);
    });
    await settle();
    expect(tree!.root.findByProps({ children: "deathNotFound" })).toBeDefined();
    await act(async () => tree!.unmount());
  });
});
