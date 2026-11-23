import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

const mockRequest = jest.fn();
const mockPush = jest.fn();
let mockOffline = false;

jest.mock("expo-router", () => ({
  useRouter: () => ({ push: mockPush }),
  useLocalSearchParams: () => ({ userId: "sup" }),
  useFocusEffect: () => undefined,
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ offline: mockOffline }) }));
jest.mock("../src/workspace/transport.native", () => ({
  createNativeWorkspaceTransport: (userId: string) => {
    mockRequest.mockClear();
    return (...args: unknown[]) => mockRequest(userId, ...args);
  },
}));
jest.mock("../src/ui", () => {
  const { createElement } = require("react");
  const group = (name: string) => ({ children, label }: { children?: React.ReactNode; label?: string }) => createElement(name, { label }, children);
  return {
    Button: ({ label, onPress }: { label: string; onPress: () => void }) => createElement("button", { "data-label": label, onClick: onPress }),
    Card: group("card"),
    Screen: ({ children, title }: { children: React.ReactNode; title: string }) => createElement("screen", { title }, children),
    Notice: group("notice"),
    ListRow: ({ label, onPress }: { label: string; onPress: () => void }) => createElement("button", { "data-label": label, onClick: onPress }),
    errorText: () => "native error",
    stateLabel: (state: string) => state,
    useUiStyles: () => ({ row: {}, card: {}, headline: {}, text: {}, muted: {}, error: {}, input: {} }),
  };
});
jest.mock("@drguptavivek/who-2022-va/native", () => ({ WhoVaQuestionControls: { SingleChoice: () => null, MultipleChoice: () => null } }));
jest.mock("../src/ConfirmDialog", () => ({ ConfirmDialog: () => null }));

import Supervision from "../src/nativeRoutes/supervision";
import { SupervisionEntry } from "../src/nativeRoutes/supervisionEntry";

const row = {
  death_id: "D1", va_sid: "VA1", unique_id: "UID-1", source: "web", project_id: "P1", state: "submitted",
  pending_flag: null, details_pending: false, deceased_name: "Asha", deceased_sex: "female", age_years: 40,
  date_of_death: "2026-09-01", unit_name: "Unit A", registered_by_name: "ANM One", started_by_name: null,
  created_at: "2026-09-02T10:00:00Z", updated_at: "2026-10-01T10:00:00Z", other_complete_interview: false,
  can_edit_death: true, can_record_consent_withdrawal: true,
};

function fakeApi(listError?: Error) {
  mockRequest.mockImplementation(async (_user: string, path: string) => {
    if (listError) throw listError;
    if (path.includes("/possible-duplicates")) return { possible_duplicates: [] };
    if (/\/cases\/D1$/.test(path)) {
      return { case: row, candidates: [], visit_note: null, edit_interview: { draft_id: "dr", va_sid: "VA1", project_id: "P1", site_id: "S1" } };
    }
    return { cases: [row], counts: { submitted: 1 }, tiles: { needs_decision: 1, overdue: 0, stuck: 0, total: 1 }, next_cursor: null };
  });
}

async function render(node: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(node); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return tree;
}

const labels = (tree: ReactTestRenderer) => tree.root.findAll((node) => node.type === "button").map((node) => node.props["data-label"]);
const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(() => { jest.clearAllMocks(); mockOffline = false; });

describe("native supervision screen", () => {
  it("lists the supervised cases over the account's own requester", async () => {
    fakeApi();
    const tree = await render(<Supervision />);
    expect(text(tree)).toContain("UID-1");
    expect(mockRequest.mock.calls[0][0]).toBe("sup");
    expect(mockRequest.mock.calls[0][1]).toContain("/api/v1/intake/supervision/cases?");
  });

  it("opens the interview and death report edits in supervisor mode and offers no withdrawal", async () => {
    fakeApi();
    const tree = await render(<Supervision />);
    // The list row: no consent-withdrawal action on the phone.
    expect(labels(tree)).toContain("Mark duplicate");
    expect(labels(tree)).not.toContain("Record consent withdrawal");
    await act(async () => { tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === "View details")[0].props.onClick(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    expect(labels(tree)).toContain("Edit interview");
    await act(async () => { tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === "Edit interview")[0].props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/supervisor-revision", params: { userId: "sup", draftId: "dr", vaSid: "VA1", projectId: "P1", siteId: "S1" } });
    await act(async () => { tree.root.findAll((node) => node.type === "button" && node.props["data-label"] === "Edit death report")[0].props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/register", params: { userId: "sup", deathId: "D1", by: "supervisor" } });
  });

  it("words a failed load with the app's error text", async () => {
    fakeApi(new Error("down"));
    expect(text(await render(<Supervision />))).toContain("native error");
  });

  it("says supervision needs a connection while offline", async () => {
    mockOffline = true;
    fakeApi();
    expect(text(await render(<Supervision />))).toContain("Supervision needs an internet connection");
  });
});

describe("Home entry", () => {
  it("opens the supervision screen for the account", async () => {
    const tree = await render(<SupervisionEntry userId="sup" />);
    await act(async () => { tree.root.findByType("button").props.onClick(); });
    expect(mockPush).toHaveBeenCalledWith({ pathname: "/supervision", params: { userId: "sup" } });
  });
});
