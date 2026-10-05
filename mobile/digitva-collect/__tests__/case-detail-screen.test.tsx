import React, { type ReactNode } from "react";
import { act, create } from "react-test-renderer";

const mockRouter = { push: jest.fn(), back: jest.fn() };
const makeBootstrap = (suffix = "") => ({
  user: { user_id: `u1${suffix}`, name: "Interviewer" },
  csrf: { header: "X-CSRFToken", token: `csrf${suffix}` },
  capabilities: { intake: true, coding: false, reviewing: false },
  links: {
    intakeCases: "/api/v1/intake/cases",
    intakeDrafts: "/api/v1/intake/drafts",
  },
});
let mockBootstrap = makeBootstrap();
const mockGetCaseDetail = jest.fn();
const mockLogContactAttempt = jest.fn();
const mockSetCaseVisit = jest.fn();
const mockStartDraft = jest.fn();

jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ deathId: "death-1" }),
  useRouter: () => mockRouter,
}));
jest.mock("../src/AppState", () => ({
  useAppState: () => ({ bootstrap: mockBootstrap }),
}));
jest.mock("../src/client/api", () => ({
  getCaseDetail: (...args: unknown[]) => mockGetCaseDetail(...args),
  logContactAttempt: (...args: unknown[]) => mockLogContactAttempt(...args),
  setCaseVisit: (...args: unknown[]) => mockSetCaseVisit(...args),
  startDraft: (...args: unknown[]) => mockStartDraft(...args),
}));
jest.mock("../src/i18n", () => ({
  t: (key: string, vars: Record<string, string> = {}) =>
    key + Object.values(vars).join(""),
}));
jest.mock("../src/deathWorkflow", () => ({
  canFollowUpDeath: () => true,
  canStartDeathInterview: (state: string) => ["registered", "in_progress"].includes(state),
  deathPhoneUrl: (phone?: string) =>
    phone ? "tel:" + phone.replace(/\s/g, "") : undefined,
}));
jest.mock("../src/ui", () => ({
  Button: ({
    label,
    onPress,
    disabled,
  }: {
    label: string;
    onPress: () => void;
    disabled?: boolean;
  }) => <button data-label={label} disabled={disabled} onClick={onPress} />,
  stateLabel: (state: string) => state,
  useUiStyles: () => ({
    card: {},
    headline: {},
    muted: {},
    text: {},
    error: {},
    row: {},
  }),
}));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "error",
}));
jest.mock("../src/web/registrationControls", () => ({
  RegistrationFieldControl: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <input
      value={value}
      onChange={(event) => onChange((event.target as HTMLInputElement).value)}
    />
  ),
}));

import CaseDetailScreen from "../src/web/newCaseDetailScreen";

const row = {
  prefill: {},
  death_id: "death-1",
  unique_id: "VA-001",
  deceased_name: "Asha Devi",
  deceased_sex: "female",
  age_years: 72,
  date_of_death: "2026-09-30",
  unit_name: "Block A",
  state: "registered",
  project_id: "P1",
  site_id: "S1",
  org_unit_id: null,
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
    address: "12 Main Road",
    house_street: "House 12",
    village_ward: "Block A",
    landmark: "Near clinic",
  },
  informant: {
    name: "Ravi Devi",
    phone: "+91 98765 43210",
    phone_2: "+91 91234 56789",
  },
  remarks: "Call after 5 pm",
  next_visit_at: null,
  last_contact_at: null,
  my_draft_id: null,
};

async function settle(): Promise<void> {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("web reported death details", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockBootstrap = makeBootstrap();
    mockGetCaseDetail.mockResolvedValue({ case: row });
    mockLogContactAttempt.mockResolvedValue({
      case: {
        death_id: "death-1",
        unique_id: "VA-001",
        status: "not_reachable",
        next_visit_at: null,
        last_contact_at: "2026-10-03T09:00:00Z",
      },
    });
    mockSetCaseVisit.mockResolvedValue({
      case: {
        death_id: "death-1",
        unique_id: "VA-001",
        status: "scheduled",
        next_visit_at: "2026-10-04T03:30:00Z",
        last_contact_at: null,
      },
    });
  });

  it("loads a later-page case directly by id without reading the paginated list", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    expect(mockGetCaseDetail).toHaveBeenCalledWith(
      "/api/v1/intake/cases",
      "death-1",
      mockBootstrap.csrf,
    );
    expect(mockGetCaseDetail).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(tree!.toJSON())).toContain("Ravi Devi");
    expect(JSON.stringify(tree!.toJSON())).toContain("12 Main Road");
    expect(JSON.stringify(tree!.toJSON())).toContain("+91 98765 43210");
    expect(JSON.stringify(tree!.toJSON())).toContain("callInformant");
    expect(JSON.stringify(tree!.toJSON())).toContain("Asha Devi");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("******3210");
    await act(async () => tree!.unmount());
  });

  it("shows the active other-draft start time without naming the interviewer", async () => {
    const startedAt = "2026-10-04T10:30:00Z";
    mockGetCaseDetail.mockResolvedValue({ case: { ...row, other_draft_active: true, other_draft_started_at: startedAt } });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain(`otherDraftActiveAt${new Date(startedAt).toLocaleString()}`);
    expect(rendered).not.toContain("interviewer name");
    await act(async () => tree!.unmount());
  });

  it("shows the complete-interview notice only when the server flag is true", async () => {
    mockGetCaseDetail.mockResolvedValue({ case: { ...row, other_complete_interview: false } });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).not.toContain("otherCompleteInterviewNotice");
    await act(async () => tree!.unmount());

    mockGetCaseDetail.mockResolvedValue({ case: { ...row, other_complete_interview: true } });
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("otherCompleteInterviewNotice");
    await act(async () => tree!.unmount());
  });

  it("uses the generic active warning for an invalid start time", async () => {
    mockGetCaseDetail.mockResolvedValue({ case: { ...row, other_draft_active: true, other_draft_started_at: "invalid" } });
    let tree: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    const rendered = JSON.stringify(tree!.toJSON());
    expect(rendered).toContain('"otherDraftActive"');
    expect(rendered).not.toContain("otherDraftActiveAt");
    await act(async () => tree!.unmount());
  });

  it("shows the server error and no contact details for an unauthorized or missing case", async () => {
    mockGetCaseDetail.mockRejectedValueOnce(new Error("not_found"));
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("error");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("+91 98765 43210");
    await act(async () => tree!.unmount());
  });

  it("refetches the full detail after a contact action", async () => {
    const updated = {
      ...row,
      state: "not_reachable",
      last_contact_at: "2026-10-04T09:00:00Z",
      remarks: "Updated after contact",
    };
    mockGetCaseDetail
      .mockResolvedValueOnce({ case: row })
      .mockResolvedValueOnce({ case: updated });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    await act(async () =>
      tree!.root
        .findAll((node) => node.props["data-label"] === "logAttempt")[0]
        .props.onClick(),
    );
    await act(async () =>
      tree!.root
        .findAll((node) => node.props["data-label"] === "outcome_reached")[0]
        .props.onClick(),
    );
    await act(async () =>
      tree!.root
        .findAll((node) => node.props["data-label"] === "save")[0]
        .props.onClick(),
    );
    await settle();
    expect(mockGetCaseDetail).toHaveBeenCalledTimes(2);
    expect(JSON.stringify(tree!.toJSON())).toContain("Updated after contact");
    await act(async () => tree!.unmount());
  });

  it("posts a contact outcome with CSRF and keeps masked phones out of tel actions", async () => {
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    const attempt = tree!.root.findAll(
      (node) => node.props["data-label"] === "logAttempt",
    )[0];
    await act(async () => attempt.props.onClick());
    const outcome = tree!.root.findAll(
      (node) => node.props["data-label"] === "outcome_reached",
    )[0];
    await act(async () => outcome.props.onClick());
    const save = tree!.root.findAll(
      (node) => node.props["data-label"] === "save",
    )[0];
    await act(async () => save.props.onClick());
    await settle();
    expect(mockLogContactAttempt).toHaveBeenCalledWith(
      "/api/v1/intake/cases",
      "death-1",
      { outcome: "reached" },
      mockBootstrap.csrf,
    );
    expect(JSON.stringify(tree!.toJSON())).not.toContain("tel:");
    await act(async () => tree!.unmount());
  });

  it("keeps contacts visible but blocks a new interview when prefill is withheld", async () => {
    const { prefill: _prefill, ...withoutPrefill } = row;
    mockGetCaseDetail.mockResolvedValue({ case: withoutPrefill });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    expect(JSON.stringify(tree.toJSON())).toContain("Ravi Devi");
    const start = tree.root.findByProps({ "data-label": "startInterview" });
    expect(start.props.disabled).toBe(true);
    await act(async () => start.props.onClick());
    expect(mockStartDraft).not.toHaveBeenCalled();
    await act(async () => tree.unmount());
  });

  it("starts a new interview when the case includes prefill", async () => {
    mockStartDraft.mockResolvedValue({ draft: { draft_id: "new-draft" } });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    const start = tree.root.findByProps({ "data-label": "startInterview" });
    expect(start.props.disabled).toBe(false);
    await act(async () => start.props.onClick());
    expect(mockStartDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", { project_id: "P1", site_id: "S1", death_id: "death-1" }, mockBootstrap.csrf);
    await act(async () => tree.unmount());
  });

  it("allows a new interview on an active case held by another interviewer when prefill is present", async () => {
    mockGetCaseDetail.mockResolvedValue({ case: { ...row, state: "in_progress", prefill: { deceased_name: "Asha Devi" }, other_draft_active: true } });
    mockStartDraft.mockResolvedValue({ draft: { draft_id: "new-draft" } });
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<CaseDetailScreen />); });
    await settle();
    const start = tree.root.findByProps({ "data-label": "startInterview" });
    expect(start.props.disabled).toBe(false);
    await act(async () => start.props.onClick());
    expect(mockStartDraft).toHaveBeenCalledWith("/api/v1/intake/drafts", { project_id: "P1", site_id: "S1", death_id: "death-1" }, mockBootstrap.csrf);
    await act(async () => tree.unmount());
  });

  it("allows resuming an owned in-progress draft", async () => {
    mockGetCaseDetail.mockResolvedValue({
      case: { ...row, prefill: undefined, state: "in_progress", my_draft_id: "draft-1" },
    });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    const resume = tree!.root.findAll(
      (node) => node.props["data-label"] === "resumeInterview",
    )[0];
    expect(resume.props.disabled).toBeFalsy();
    await act(async () => resume.props.onClick());
    expect(mockRouter.push).toHaveBeenCalledWith({
      pathname: "/interview",
      params: { draftId: "draft-1" },
    });
    await act(async () => tree!.unmount());
  });

  it("ignores a previous session response after the bootstrap changes", async () => {
    let resolveOld!: (value: { case: typeof row }) => void;
    const oldResponse = new Promise<{ case: typeof row }>((resolve) => {
      resolveOld = resolve;
    });
    mockGetCaseDetail
      .mockImplementationOnce(() => oldResponse)
      .mockResolvedValueOnce({
        case: {
          ...row,
          deceased: { ...row.deceased, name: "New session case" },
        },
      });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
      await Promise.resolve();
    });
    mockBootstrap = makeBootstrap("/new");
    await act(async () => {
      tree!.update(<CaseDetailScreen />);
      await Promise.resolve();
    });
    await settle();
    resolveOld({ case: row });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("New session case");
    expect(JSON.stringify(tree!.toJSON())).not.toContain("Asha Devi");
    await act(async () => tree!.unmount());
  });

  it("clears the busy state when the scope changes during a mutation", async () => {
    let resolveAction!: (value: {
      case: { death_id: string; unique_id: string; status: string };
    }) => void;
    const pendingAction = new Promise<{
      case: { death_id: string; unique_id: string; status: string };
    }>((resolve) => {
      resolveAction = resolve;
    });
    mockLogContactAttempt.mockImplementationOnce(() => pendingAction);
    mockGetCaseDetail.mockResolvedValue({ case: row });
    let tree: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<CaseDetailScreen />);
    });
    await settle();
    await act(async () =>
      tree!.root
        .findAll((node) => node.props["data-label"] === "logAttempt")[0]
        .props.onClick(),
    );
    await act(async () =>
      tree!.root
        .findAll((node) => node.props["data-label"] === "outcome_reached")[0]
        .props.onClick(),
    );
    await act(async () => {
      tree!.root
        .findAll((node) => node.props["data-label"] === "save")[0]
        .props.onClick();
      await Promise.resolve();
    });
    mockBootstrap = makeBootstrap("/changed");
    await act(async () => {
      tree!.update(<CaseDetailScreen />);
      await Promise.resolve();
    });
    await settle();
    const start = tree!.root.findAll(
      (node) => node.props["data-label"] === "startInterview",
    )[0];
    expect(start.props.disabled).toBeFalsy();
    resolveAction({
      case: {
        death_id: "death-1",
        unique_id: "VA-001",
        status: "not_reachable",
      },
    });
    await settle();
    expect(JSON.stringify(tree!.toJSON())).toContain("Asha Devi");
    await act(async () => tree!.unmount());
  });
});
