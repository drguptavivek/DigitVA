import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockAccount = { user_id: "u1", name: "Interviewer" };
const mockDb = {};
const mockRouter = { push: jest.fn(), back: jest.fn(), replace: jest.fn() };
const mockReload = jest.fn();
let mockParams: {
  userId: string;
  projectId?: string;
  siteId?: string;
  draftId?: string;
  clientDeathId?: string;
  refresh?: string;
} = { userId: "u1" };
let mockReference: unknown;
let mockCachedReference: unknown;
let mockCachedCases: unknown[] = [];

function pack(mode = "both", projectId = "P1") {
  const project = {
    project_id: projectId,
    project_name: `Project ${projectId}`,
    web_intake_mode: mode,
    sites: [
      {
        project_id: projectId,
        site_id: "S1",
        site_name: "Site 1",
        web_intake_mode: mode,
      },
    ],
    form_options: {
      default_locale: "en",
      available_locales: [{ code: "en", label: "English" }],
    },
    prefill_policy: {
      direct: {},
      units: {},
      answer_fields: {},
      locked_fields: [],
    },
  };
  return {
    bootstrap: {
      user: mockAccount,
      instrument_version: "v1",
      projects: [project],
    },
    projects: [{ project, units: { scoped: false, levels: [], units: [] } }],
  };
}

mockReference = pack();

jest.mock("expo-router", () => ({
  Redirect: () => null,
  useRouter: () => mockRouter,
  useLocalSearchParams: () => mockParams,
  useFocusEffect: (callback: () => undefined | (() => void)) => {
    const ReactActual = jest.requireActual("react") as typeof React;
    ReactActual.useEffect(callback, [callback]);
  },
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({
    accounts: [mockAccount],
    reload: mockReload,
    lockNow: jest.fn(),
    activity: jest.fn(),
    onBeforeLock: jest.fn(() => jest.fn()),
    chooseUiLocale: jest.fn(async () => undefined),
  }),
}));
jest.mock("../src/interviewerDb", () => ({
  isUnlocked: () => true,
  openInterviewerDb: jest.fn(async () => mockDb),
}));
jest.mock("../src/drafts", () => ({
  listDrafts: jest.fn(async () => []),
  listActions: jest.fn(async () => []),
  listCases: jest.fn(async () => []),
  listRegistrations: jest.fn(async () => []),
  getDraftRow: jest.fn(async () => null),
  getMeta: jest.fn(async () => undefined),
  setMeta: jest.fn(async () => undefined),
  createDraftStore: jest.fn(() => ({
    save: jest.fn(),
    load: jest.fn(),
    remove: jest.fn(),
  })),
  markCompleted: jest.fn(),
}));
jest.mock("../src/cases", () => {
  const actual = jest.requireActual("../src/cases") as Record<string, unknown>;
  return {
    ...actual,
    listCases: jest.fn(async () => mockCachedCases),
    listActions: jest.fn(async () => []),
    listRegistrations: jest.fn(async () => []),
    getRegistration: jest.fn(async () => undefined),
    saveRegistration: jest.fn(async () => undefined),
    resolveDraftHost: jest.fn(async () => ({
      projectId: "P1",
      siteId: "S1",
      binding: {},
      prefill: undefined,
    })),
  };
});
jest.mock("../src/sync", () => ({
  getCachedReferenceData: jest.fn(async () => mockCachedReference),
  refreshReferenceData: jest.fn(async () => mockReference),
  refreshCases: jest.fn(async () => undefined),
  syncInterviewer: jest.fn(async () => ({
    sent: 0,
    failed: 0,
    remaining: 0,
    supersededUniqueIds: [],
  })),
  fetchCasePage: jest.fn(
    async (_user: string, projectId: string, options: { cursor?: string }) => ({
      cases: [
        {
          death_id: options.cursor ? "d2" : "d1",
          project_id: projectId,
          unique_id: "VA-1",
          state: "registered",
          deceased_name: "Online",
          deceased_sex: "female",
          age_years: 40,
          date_of_death: null,
          site_id: "S1",
          org_unit_id: null,
          unit_name: null,
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
          informant_phone_masked: null,
          informant_phone_2_masked: null,
        },
      ],
      next_cursor: options.cursor ? null : "next",
    }),
  ),
  targetsFrom: (project: {
    sites: Array<{ site_id: string; site_name?: string; project_id: string }>;
  }) =>
    project.sites.map((site) => ({
      key: site.site_id,
      label: site.site_name ?? site.site_id,
      siteId: site.site_id,
      projectId: site.project_id,
    })),
  startsDirectly: (
    project: { sites: Array<{ site_id: string; web_intake_mode?: string }> },
    siteId: string,
  ) =>
    project.sites.some(
      (site) =>
        site.site_id === siteId &&
        ["direct", "both"].includes(site.web_intake_mode ?? ""),
    ),
  registersDeaths: (project: { web_intake_mode: string }) =>
    ["death_register", "both"].includes(project.web_intake_mode),
  translationsFor: jest.fn(async () => null),
  isUploadable: () => true,
}));
jest.mock("../src/i18n", () => ({
  ...jest.requireActual("../src/i18n"),
  t: (key: string, values?: Record<string, string | number>) => {
    if (key === "draftHashMismatch") {
      return "This interview was already uploaded; your later edits were not applied.";
    }
    if (key === "draftHashInvalidAttention") {
      return "This interview could not be verified. Open it, review the answers, and try sending it again.";
    }
    if (key === "storedInterviewId") {
      return `Stored interview: ${values?.uniqueId ?? ""}`;
    }
    if (key === "supersededInterviewNotice") {
      return "A teammate’s interview of this case was submitted first; yours is kept.";
    }
    return key;
  },
  uiLocale: () => "en",
}));
jest.mock("../src/ui", () => {
  const ReactActual = jest.requireActual("react") as typeof React;
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
      ReactActual.createElement(
        "button",
        { "data-label": label, disabled, onClick: onPress },
        label,
      ),
    Row: ({ children }: { children: ReactNode }) =>
      ReactActual.createElement("div", null, children),
    Screen: ({ children }: { children: ReactNode }) =>
      ReactActual.createElement("main", null, children),
    errorText: () => "error",
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
jest.mock("../src/platform", () => ({ platformServices: {} }));
jest.mock("../src/prefill", () => ({ initialDataFromPrefill: () => ({}) }));
jest.mock(
  "@drguptavivek/who-2022-va/native",
  () => ({
    WhoVaForm: () => null,
    WhoVaQuestionControls: {
      Date: () => null,
      Integer: () => null,
      Text: () => null,
    },
  }),
  { virtual: true },
);
jest.mock(
  "@drguptavivek/who-2022-va",
  () => ({
    createWhoVa2022Instrument: jest.fn(() => ({ sections: [], questions: [] })),
    resolveUiMessages: () => ({}),
    WHO_VA_BUILT_IN_UI_TRANSLATIONS: {},
  }),
  { virtual: true },
);

import Register from "../src/nativeRoutes/register";
import Worklist from "../src/nativeRoutes/worklist";
import {
  fetchCasePage,
  getCachedReferenceData,
  refreshReferenceData,
  refreshCases,
  syncInterviewer,
} from "../src/sync";
import { saveRegistration } from "../src/cases";

const settle = async () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

beforeEach(() => {
  jest.clearAllMocks();
  mockParams = { userId: "u1" };
  mockReference = pack();
  mockCachedReference = mockReference;
  mockCachedCases = [];
  (jest.requireMock("../src/drafts").listDrafts as jest.Mock).mockImplementation(
    async () => [],
  );
  (getCachedReferenceData as jest.Mock).mockImplementation(
    async () => mockReference,
  );
  (refreshReferenceData as jest.Mock).mockImplementation(
    async () => mockReference,
  );
});

describe("native project-aware routes", () => {
  it("keeps project settings separate and passes the selected project to direct starts", async () => {
    const p2 = pack("direct", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...p2.bootstrap.projects],
      },
      projects: [...first.projects, ...p2.projects],
    };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    expect(
      tree!.root.findByProps({ "data-label": "Project P2" }),
    ).toBeDefined();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "Project P2" }).props.onClick(),
    );
    await act(async () =>
      tree!.root.findByProps({ "data-label": "newInterview" }).props.onClick(),
    );
    await act(async () =>
      tree!.root.findByProps({ "data-label": "Site 1" }).props.onClick(),
    );
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ projectId: "P2" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("uses the selected project's mode for registration and validates before saving", async () => {
    mockParams = { userId: "u1", projectId: "P1", clientDeathId: "local-1" };
    (
      jest.requireMock("../src/cases").getRegistration as jest.Mock
    ).mockResolvedValueOnce({
      client_death_id: "local-1",
      project_id: "P1",
      site_id: "S1",
      org_unit_id: null,
      state: "pending",
      created_at: "2026-10-03T00:00:00.000Z",
      fields: {
        deceased_name: "Asha",
        deceased_sex: "female",
        date_of_death: "2026-09-30",
        date_of_birth: "1980-01-01",
      },
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Register />);
    });
    await settle();
    expect(
      tree!.root.findByProps({ "data-label": "registerSaveStart" }).props
        .disabled,
    ).toBe(false);
    await act(async () =>
      tree!.root
        .findByProps({ "data-label": "registerSaveStart" })
        .props.onClick(),
    );
    expect(saveRegistration).toHaveBeenCalledWith(
      mockDb,
      expect.objectContaining({ project_id: "P1" }),
    );
    await act(async () => tree!.unmount());
  });

  it("downloads active cases again after the forced post-login settings refresh", async () => {
    mockParams = { userId: "u1", refresh: "1" };
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    expect(refreshCases).toHaveBeenCalledWith("u1", mockDb);
    await act(async () => tree!.unmount());
  });

  it("keeps a hash-mismatched upload completed and shows the stored interview id", async () => {
    const draft = {
      id: "draft-mismatch",
      project_id: "P1",
      completed: 1,
      updated_at: "2026-10-04T00:00:00.000Z",
      unique_id: "VA-LOCAL",
      upload_issue: "hash_mismatch",
      upload_issue_unique_id: "VA-STORED",
    };
    (
      jest.requireMock("../src/drafts").listDrafts as jest.Mock
    ).mockResolvedValue([draft]);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(
      "This interview was already uploaded; your later edits were not applied.",
    );
    expect(rendered).toContain("Stored interview: VA-STORED");
    const draftButton = tree!.root
      .findAllByProps({ accessibilityRole: "button" })
      .find(
        (button) =>
          button.props.disabled === true && button.props.onPress === undefined,
      );
    expect(draftButton).toBeDefined();
    expect(draftButton!.props.disabled).toBe(true);
    expect(mockRouter.push).not.toHaveBeenCalledWith(
      expect.objectContaining({ pathname: "/form" }),
    );
    await act(async () => tree!.unmount());
  });

  it("marks an invalid-hash draft for attention and leaves it editable", async () => {
    const draft = {
      id: "draft-invalid",
      project_id: "P1",
      completed: 0,
      updated_at: "2026-10-04T00:00:00.000Z",
      unique_id: "VA-LOCAL",
      upload_issue: "answers_hash_invalid",
      upload_issue_unique_id: null,
    };
    (
      jest.requireMock("../src/drafts").listDrafts as jest.Mock
    ).mockResolvedValue([draft]);
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain(
      "This interview could not be verified. Open it, review the answers, and try sending it again.",
    );
    const draftButton = tree!.root
      .findAllByProps({ accessibilityRole: "button" })
      .find((button) => button.props.disabled === false);
    expect(draftButton).toBeDefined();
    await act(async () => draftButton!.props.onPress());
    expect(mockRouter.push).toHaveBeenCalledWith(
      expect.objectContaining({
        pathname: "/form",
        params: expect.objectContaining({ draftId: "draft-invalid" }),
      }),
    );
    await act(async () => tree!.unmount());
  });

  it("shows a superseded notice with each unique id after sync", async () => {
    (syncInterviewer as jest.Mock).mockResolvedValueOnce({
      sent: 1,
      failed: 0,
      remaining: 0,
      supersededUniqueIds: ["VA-FIRST"],
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "sync" }).props.onClick(),
    );
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(
      "A teammate’s interview of this case was submitted first; yours is kept.",
    );
    expect(rendered).toContain("Stored interview: VA-FIRST");
    await act(async () => tree!.unmount());
  });

  it("keeps a superseded notice when a later sync request fails", async () => {
    (syncInterviewer as jest.Mock).mockImplementationOnce(
      async (
        _userId: string,
        _db: unknown,
        onSuperseded?: (uniqueId: string) => void,
      ) => {
        onSuperseded?.("VA-FIRST");
        throw new TypeError("Network request failed");
      },
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "sync" }).props.onClick(),
    );
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(
      "A teammate’s interview of this case was submitted first; yours is kept.",
    );
    expect(rendered).toContain("Stored interview: VA-FIRST");
    await act(async () => tree!.unmount());
  });

  it("re-reads the sanitized pack and clears visible revoked-project data after refresh failure", async () => {
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const second = pack("both", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...second.bootstrap.projects],
      },
      projects: [...first.projects, ...second.projects],
    };
    mockCachedReference = mockReference;
    mockCachedCases = [
      {
        death_id: "removed",
        project_id: "P2",
        unique_id: "VA-REMOVED",
        state: "registered",
        deceased: {
          name: "Removed contact",
          sex: null,
          age_years: null,
          date_of_birth: null,
          date_of_birth_partial: null,
          date_of_death: null,
          place_of_death: null,
        },
        household_address: {
          address: null,
          house_street: null,
          village_ward: null,
          landmark: null,
        },
        informant: { name: null, phone: null, phone_2: null },
        remarks: null,
        prefill: {},
        links: { self: "", attempts: "", visit: "" },
        site_id: "S1",
        org_unit_id: null,
        unit_name: null,
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
      },
    ];
    const refresh = refreshReferenceData as jest.Mock;
    refresh.mockImplementationOnce(async () => {
      mockCachedReference = pack("both", "P1");
      mockCachedCases = [];
      throw new Error("settings_unavailable");
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await settle();
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Removed contact");
    await act(async () => tree!.unmount());
  });

  it("fetches reported-death pages online by project and keeps pagination in memory", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findAllByProps({ "data-label": "refresh" })[0].props.onClick(),
    );
    await settle();
    expect(fetchCasePage).toHaveBeenCalledWith("u1", "P1", { limit: 50 });
    await act(async () => tree!.unmount());
  });

  it("drops a delayed online page when the interviewer switches projects", async () => {
    const first = pack("both", "P1") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    const second = pack("both", "P2") as {
      bootstrap: { projects: unknown[] };
      projects: unknown[];
    };
    mockReference = {
      bootstrap: {
        ...first.bootstrap,
        projects: [...first.bootstrap.projects, ...second.bootstrap.projects],
      },
      projects: [...first.projects, ...second.projects],
    };
    let resolvePage!: (page: unknown) => void;
    (fetchCasePage as jest.Mock).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolvePage = resolve;
        }),
    );
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<Worklist />);
    });
    await settle();
    await act(async () =>
      tree!.root.findAllByProps({ "data-label": "refresh" })[0].props.onClick(),
    );
    await settle();
    await act(async () =>
      tree!.root.findByProps({ "data-label": "Project P2" }).props.onClick(),
    );
    resolvePage({
      cases: [
        {
          death_id: "old",
          project_id: "P1",
          unique_id: "OLD",
          state: "registered",
          deceased_name: "Old project contact",
        },
      ],
      next_cursor: null,
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Old project contact");
    await act(async () => tree!.unmount());
  });
});
