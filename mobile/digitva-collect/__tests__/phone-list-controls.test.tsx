import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, kind }: { label: string; onPress?: () => void; kind?: string }) =>
    (jest.requireActual("react") as typeof React).createElement("button", { "data-label": label, "data-kind": kind, onClick: onPress }, label),
  useUiStyles: () => ({ card: {}, error: {}, muted: {}, text: {} }),
  stateLabel: (s: string) => s,
}));
jest.mock("../src/web/LocationCapture", () => ({ MapsPinButton: () => null }));

import { InterviewCard, InterviewsView } from "../src/nativeRoutes/worklistParts";
import { buildInterviewItems, formatWhen } from "../src/ui/interviewRows";
import { controlText } from "../src/theme";
import { setUiLocale } from "../src/i18n";
import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

let tree: ReactTestRenderer;
const render = async (node: React.ReactElement) => { await act(async () => { tree = create(node); }); return tree; };
afterEach(async () => { await act(async () => tree?.unmount()); setUiLocale("en"); });

const draft = (id: string, extra = {}) => ({ id, project_id: "P1", site_id: "S1", org_unit_id: null, completed: 0, updated_at: "2026-10-23T13:40:00.000Z", death_id: null, unique_id: null, client_death_id: null, ...extra }) as never;
const sources = (extra = {}) => ({ drafts: [], registrations: [], cases: [], onlineCases: [], submitted: [], revisions: [], ...extra });
const noop = () => undefined;
const item = (extra = {}) => buildInterviewItems(sources({ drafts: [draft("7b010f05-aaaa", extra)] }))[0];

describe("interview card", () => {
  it("puts Continue first and primary, and Delete draft after it as a non-primary outline action", async () => {
    await render(<InterviewCard item={item()} onAction={noop} onRetryDemo={noop} onDelete={noop} />);
    const order = tree.root.findAll((n) => n.props["data-label"] || (n.props.accessibilityLabel === "Delete draft" && typeof n.props.onPress === "function"));
    expect(order[0].props["data-label"]).toBe("Resume");
    expect(order[0].props["data-kind"]).not.toBe("danger");
    expect(order[1].props.accessibilityLabel).toBe("Delete draft");
    expect(order[1].props.style.minHeight).toBeGreaterThanOrEqual(44);
    expect(order[1].props.style.backgroundColor).toBeUndefined();
    expect(tree.root.findAll((n) => n.props["data-label"] === "Delete draft")).toHaveLength(0);
  });

  it("titles an unnamed draft Untitled interview with the short id as muted text", () => {
    const it = item();
    expect(it.title).toBe("Untitled interview");
    expect(it.caseId).toBe("7b010f05");
  });

  it("titles a direct-start draft from the name in its own answers; a linked case name still wins", () => {
    const named = item({ deceased_name: "Mohan Testcase" });
    expect(named.title).toBe("Mohan Testcase");
    expect(named.caseId).toBe("7b010f05"); // no case id yet: the short local id stays
    expect(item({ deceased_name: "Mohan Testcase", unique_id: "A-1" })).toMatchObject({ title: "Mohan Testcase", caseId: "A-1" });
    expect(item({ deceased_name: null }).title).toBe("Untitled interview");
    const linked = buildInterviewItems(sources({
      drafts: [draft("d1", { death_id: "C1", deceased_name: "Mohan Testcase" })],
      cases: [{ death_id: "C1", unique_id: "AAM01-C1", project_id: "P1", site_id: "S1", org_unit_id: null, unit_name: "CHC", state: "registered", source: "reported", my_draft_id: null, updated_at: "2026-10-01T00:00:00Z", deceased: { name: "Ramesh Kumar" }, household_address: {} } as never],
    }))[0];
    expect(linked.title).toBe("Ramesh Kumar");
  });

  it("shows the key time per state, formatted and never raw ISO", async () => {
    const started = item({ started_at: "2026-10-23T09:15:00.000Z" });
    expect(started.timeText).toMatch(/^Started .*2026/);
    expect(started.timeText).not.toMatch(/T\d\d:/);
    expect(item().timeText).toMatch(/^Last saved /);
    expect(item({ completed: 1, completed_at: "2026-10-23T10:00:00.000Z" }).timeText).toMatch(/^Completed /);
    const sent = buildInterviewItems(sources({ submitted: [{ draft_id: "s1", project_id: "P1", site_id: "S1", death_id: null, va_sid: "x", unique_id: "A-1", updated_at: "2026-10-22T08:00:00Z" }] }))[0];
    expect(sent.timeText).toMatch(/^Submitted /);
    expect(formatWhen("garbage")).toBe("");
    setUiLocale("hi");
    expect(item({ started_at: "2026-10-23T09:15:00.000Z" }).timeText).toMatch(/^शुरू किया: /);
    await render(<InterviewCard item={item({ started_at: "2026-10-23T09:15:00.000Z" })} onAction={noop} onRetryDemo={noop} />);
    expect(tree.root.findAllByProps({ testID: "time-line" }).length).toBeGreaterThan(0);
  });
});

describe("controls", () => {
  it("centre text on Android without font padding", () => {
    expect(controlText).toMatchObject({ includeFontPadding: false, textAlignVertical: "center", textAlign: "center" });
  });

  it("filter chips are single line, 44dp, with the centring style", async () => {
    await render(<InterviewsView loaded offline={false} items={[item()]} canRegister refreshing={false} busy={false} canRefresh hasMore={false} loadingMore={false} loadFailed={false} onAction={noop} onRetryDemo={noop} onRegister={noop} onRefresh={noop} onSend={noop} onLoadMore={noop} />);
    const chips = tree.root.findAll((n) => n.props.accessibilityRole === "tab" && typeof n.props.onPress === "function");
    expect(chips).toHaveLength(5);
    for (const chip of chips) {
      expect(chip.props.style.minHeight).toBeGreaterThanOrEqual(44);
      const label = chip.findAllByType(Text)[0];
      expect(label.props.numberOfLines).toBe(1);
      expect(label.props.style).toMatchObject({ includeFontPadding: false, textAlignVertical: "center" });
      expect(label.props.style.lineHeight).toBeGreaterThanOrEqual(14 * 1.4);
    }
  });

  it("has Hindi strings for every new key", () => {
    for (const key of ["untitledInterview", "interviewStarted", "interviewLastSaved", "interviewCompleted", "interviewSubmittedAt", "interviewSaved"] as const) {
      expect(en[key]).toBeTruthy();
      expect(hi[key]).toBeTruthy();
    }
  });
});
