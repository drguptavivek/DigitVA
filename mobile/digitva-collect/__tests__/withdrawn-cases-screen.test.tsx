import React, { type ReactNode } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

const mockRequest = jest.fn();

jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: { csrf: { header: "X-CSRFToken", token: "t" }, access: { roles: ["admin"] } } }) }));
jest.mock("../src/workspace/transport.web", () => ({ createWebWorkspaceTransport: () => mockRequest }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: ReactNode }) => <>{children}</>,
  browserErrorText: () => "server error",
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => (
    <button data-label={label} disabled={disabled} onClick={onPress} />
  ),
  stateLabel: (state: string) => state,
  useUiStyles: () => ({ row: {}, card: {}, headline: {}, text: {}, muted: {}, error: {}, input: {} }),
}));
jest.mock("@drguptavivek/who-2022-va/native", () => ({ WhoVaQuestionControls: { SingleChoice: () => null, MultipleChoice: () => null } }));
jest.mock("../src/ConfirmDialog", () => ({ ConfirmDialog: () => null }));

import WithdrawnCasesScreen from "../src/web/WithdrawnCasesScreen";

const ROW = {
  withdrawal_id: "W1", death_id: "D1", unique_id: "UID-1", project_id: "P1", project_name: "Project One",
  requested_on: "2026-11-01", recorded_at: "2026-11-02T10:00:00+00:00", channel: "phone", recorded_by_name: "Dana DM", undone: false,
};
const DETAIL = {
  case: {
    death_id: "D1", va_sid: "VA1", unique_id: "UID-1", project_id: "P1", state: "submitted", pending_flag: null, details_pending: false,
    deceased_name: "Asha", deceased_sex: "female", age_years: 40, date_of_death: "2026-09-01", unit_name: "Unit A",
    registered_by_name: "ANM", started_by_name: null, updated_at: null, other_complete_interview: false, source: "register",
    consent_withdrawn: true,
    consent_withdrawal: { requested_by: "informant's son", requested_on: "2026-11-01", channel: "phone", contact_reference: null, note: null, recorded_at: "2026-11-02T10:00:00+00:00" },
  },
  candidates: [], visit_note: null,
};

const settle = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const buttons = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.type === "button" && n.props["data-label"] === label);
async function press(tree: ReactTestRenderer, label: string) {
  const found = buttons(tree, label);
  if (!found[0]) throw new Error(`no button "${label}"`);
  await act(async () => { found[0].props.onClick(); });
  await settle();
}
const texts = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

async function render() {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<WithdrawnCasesScreen />); });
  await settle();
  return tree;
}

describe("WithdrawnCasesScreen", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRequest.mockImplementation(async (path: string, init?: { method?: string }) => {
      if (init?.method === "POST") return { case: { ...DETAIL.case, consent_withdrawn: false, consent_withdrawal: undefined } };
      if (path.includes("/possible-duplicates")) return { possible_duplicates: [] };
      if (/\/cases\/D1$/.test(path)) return DETAIL;
      return { withdrawals: [ROW], next_cursor: null };
    });
  });

  it("lists withdrawn cases without respondent text, then opens the sealed case and undoes the record", async () => {
    const tree = await render();
    expect(mockRequest.mock.calls[0][0]).toBe("/api/v1/admin/consent-withdrawals?limit=100");
    const list = texts(tree);
    expect(list).toContain("UID-1");
    expect(list).toContain("Project One");
    expect(list).toContain("Dana DM");
    expect(list).not.toContain("informant's son");

    await press(tree, en.withdrawnCasesOpen);
    expect(texts(tree)).toContain(en.supervisionWithdrawnBanner);
    expect(texts(tree)).toContain("informant's son");

    await press(tree, en.supervisionWithdrawalUndo);
    const input = tree.root.findAll((n) => typeof n.props.onChangeText === "function")[0];
    act(() => input.props.onChangeText("wrong case"));
    await press(tree, en.supervisionWithdrawalUndo);

    const post = mockRequest.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/intake/supervision/cases/D1/consent-withdrawal/undo");
    expect(post?.[1].json).toEqual({ reason: "wrong case" });
    // Back on a freshly loaded list.
    expect(mockRequest.mock.calls.filter(([path]) => String(path).startsWith("/api/v1/admin/consent-withdrawals")).length).toBe(2);
    expect(texts(tree)).toContain(en.withdrawnCasesIntro);
  });

  it("asks for undone records and a project when told to", async () => {
    const tree = await render();
    await press(tree, en.withdrawnCasesIncludeUndone);
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/admin/consent-withdrawals?limit=100&include_undone=1");
    const input = tree.root.findAll((n) => typeof n.props.onChangeText === "function")[0];
    act(() => input.props.onChangeText("P1"));
    await press(tree, en.withdrawnCasesApply);
    expect(mockRequest.mock.calls.at(-1)?.[0]).toBe("/api/v1/admin/consent-withdrawals?limit=100&project_id=P1&include_undone=1");
  });

  it("has Hindi for every new key", () => {
    for (const key of ["navWithdrawnCases", "withdrawnCasesIntro", "withdrawnCasesEmpty", "withdrawnCasesProject", "withdrawnCasesApply",
      "withdrawnCasesIncludeUndone", "withdrawnCasesRow", "withdrawnCasesUndone", "withdrawnCasesOpen", "supervisionWithdrawalDetail"]) {
      expect((hi as Record<string, string>)[key]).toBeTruthy();
      expect((en as Record<string, string>)[key]).toBeTruthy();
    }
  });
});
