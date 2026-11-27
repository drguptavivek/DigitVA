import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("../src/ui", () => require("../test-support/uiMockExtras").withUiExtras({
  Button: ({ label, onPress }: { label: string; onPress?: () => void }) =>
    (jest.requireActual("react") as typeof React).createElement("button", { "data-label": label, onClick: onPress }, label),
  useUiStyles: () => ({ card: {}, error: {}, muted: {}, text: {} }),
}));
jest.mock("../src/web/LocationCapture", () => ({ MapsPinButton: () => null }));

import { CaseCard } from "../src/ui/CaseCard";
import { caseNumberLabel, caseSupportText } from "../src/ui/caseSupport";
import { InterviewCard } from "../src/nativeRoutes/worklistParts";
import { buildInterviewItems } from "../src/ui/interviewRows";
import { APP_VERSION } from "../src/appVersion";

let tree: ReactTestRenderer;
const render = async (node: React.ReactElement) => { await act(async () => { tree = create(node); }); return tree; };
afterEach(async () => { await act(async () => tree?.unmount()); });
const icon = (label: string) => tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function");
const shown = () => tree.root.findAllByType(Text).map((n) => [n.props.children].flat(3).filter((c) => typeof c === "string").join("")).join("\n");
const noop = () => undefined;
const base = { title: "Asha", badges: [], actions: null };

describe("caseSupportText", () => {
  const text = caseSupportText({ caseId: "Case 000274", projectId: "UNSW01", unit: "SC-AAM 1", ageYears: 61, sex: "female", status: "To do" });
  it("carries the case, project, unit, age, sex, status and the app version", () => {
    expect(text).toBe(`Case 000274\nUNSW01 · SC-AAM 1\nAge: 61 · Sex: female\nStatus: To do\nApp ${APP_VERSION}`);
  });
  it("never has the name or phone (the inputs have no such field)", () => {
    expect(text).not.toContain("Asha");
    expect(text).not.toMatch(/\d{10}/);
  });
  it("shortens a masked id and leaves other shapes", () => {
    expect(caseNumberLabel("PHC01-000274_172313647")).toBe("Case 000274");
    expect(caseNumberLabel("A-1")).toBe("A-1");
  });
});

describe("CaseCard icons", () => {
  it("renders call then copy when given, and neither when absent", async () => {
    await render(<CaseCard {...base} copyText="x" copyLabel="Copy it" onCall={noop} callLabel="Call it" />);
    expect(icon("Copy it")).toHaveLength(1);
    expect(icon("Call it")).toHaveLength(1);
    await act(async () => tree.update(<CaseCard {...base} />));
    expect(icon("Copy it")).toHaveLength(0);
    expect(icon("Call it")).toHaveLength(0);
  });
  it("puts the area on the ID line in idBelowTitle mode and not in the Died line", async () => {
    await render(<CaseCard {...base} idBelowTitle caseId="Case 000274" area="SC-AAM 1" dateOfDeath="2026-01-02" />);
    expect(shown()).toContain("Case 000274 · SC-AAM 1");
    expect(tree.root.findAllByProps({ testID: "case-fact-area" })).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "case-fact-died" }).length).toBeGreaterThan(0);
  });
});

describe("InterviewCard icons", () => {
  const row = (extra = {}) => ({ death_id: "d1", unique_id: "PHC01-000274_1", project_id: "P1", unit_name: "CHC", state: "registered", updated_at: "2026-10-01T00:00:00Z", deceased_name: "Asha Devi", age_years: 61, deceased_sex: "female", date_of_death: "2026-07-01", ...extra });
  const item = (extra = {}) => buildInterviewItems({ drafts: [], registrations: [], cases: [], submitted: [], revisions: [], onlineCases: [row(extra) as never] })[0];

  it("has a copy icon whose text omits the name, and a call icon only for a death with a phone", async () => {
    const onCall = jest.fn(async () => undefined);
    await render(<InterviewCard item={item({ has_informant_phone: true })} onAction={noop} onRetryDemo={noop} onCall={onCall} />);
    const copy = tree.root.findAll((n) => n.props.accessibilityLabel === "Copy details of Case 000274" && typeof n.props.onPress === "function");
    expect(copy).toHaveLength(1);
    expect(icon("Call informant")).toHaveLength(1);
    await act(async () => { icon("Call informant")[0].props.onPress(); });
    expect(onCall).toHaveBeenCalledWith(expect.objectContaining({ deathId: "d1" }));
    await act(async () => tree.update(<InterviewCard item={item()} onAction={noop} onRetryDemo={noop} onCall={onCall} />));
    expect(icon("Call informant")).toHaveLength(0);
  });

  it("shows only the year when the row says the date of death is year-only", async () => {
    await render(<InterviewCard item={item({ date_of_death: "2026-07-01", date_of_death_year_only: true })} onAction={noop} onRetryDemo={noop} />);
    expect(shown()).toContain("Died: 2026");
    await act(async () => tree.update(<InterviewCard item={item({ date_of_death: "2026-07-01" })} onAction={noop} onRetryDemo={noop} />));
    expect(shown()).not.toContain("Died: 2026\n");
    expect(shown()).toContain("Jul");
  });
});
