import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress?: () => void; disabled?: boolean }) =>
    (jest.requireActual("react") as typeof React).createElement("button", { "data-label": label, disabled, onClick: onPress }, label),
  useUiStyles: () => ({ card: {}, error: {}, muted: {}, text: {} }),
  stateLabel: (s: string) => s,
}));
jest.mock("../src/web/LocationCapture", () => ({ MapsPinButton: () => null }));

import { CaseCard as SharedCaseCard } from "../src/ui/CaseCard";
import { CaseCard as WebCaseCard, formatDisplayTimestamp, sexLabel } from "../src/web/DeathsList";
import { HomeView, InterviewsView, SitePickerSheet } from "../src/nativeRoutes/worklistParts";
import { OfflineNotice, SkeletonCards, StateView } from "../src/ui/StateView";
import { buildInterviewItems, interviewCounts } from "../src/ui/interviewRows";
import { homeSummary } from "../src/ui/homeSummary";

const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON(), (k, v) => (k === "data" && Array.isArray(v) ? undefined : v));
/** Every string a Text node shows (the Modal host cannot be serialised, so the sheet tests read text this way). */
const shown = (tree: ReactTestRenderer) =>
  tree.root.findAllByType(Text).map((node) => [node.props.children].flat(3).filter((c) => typeof c === "string").join("")).join("\n");
const labelled = (tree: ReactTestRenderer, label: string) => tree.root.findAll((n) => n.props["data-label"] === label);
const pressable = (tree: ReactTestRenderer, label: string) =>
  tree.root.findAll((n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function")[0];
let tree: ReactTestRenderer;
const render = async (node: React.ReactElement) => { await act(async () => { tree = create(node); }); return tree; };
afterEach(async () => { await act(async () => tree?.unmount()); });

const caseRow = (id: string, name: string, extra = {}) => ({
  death_id: id, unique_id: `AAM01-${id}`, project_id: "P1", site_id: "S1", org_unit_id: null, unit_name: "CHC Bhoranj", state: "registered",
  source: "reported", my_draft_id: null, updated_at: "2026-10-01T00:00:00Z",
  deceased: { name, sex: "male", age_years: 68, date_of_death: "2026-09-12" }, household_address: { village_ward: "Hamirpur" }, ...extra,
}) as never;
const draft = (id: string, extra = {}) => ({ id, project_id: "P1", site_id: "S1", org_unit_id: null, completed: 0, updated_at: "2026-10-23T13:40:00.000Z", death_id: null, unique_id: null, client_death_id: null, ...extra }) as never;
const sources = (extra = {}) => ({ drafts: [], registrations: [], cases: [], onlineCases: [], submitted: [], revisions: [], ...extra });

const noop = () => undefined;
const interviewsProps = (items: ReturnType<typeof buildInterviewItems>, extra = {}) => ({
  loaded: true, offline: false, items, canRegister: true, refreshing: false, busy: false, canRefresh: true, hasMore: false,
  loadingMore: false, loadFailed: false, onAction: noop, onRetryDemo: noop, onRegister: noop, onRefresh: noop, onSend: noop, onLoadMore: noop, ...extra,
});

describe("CaseCard", () => {
  it("is the one card: the web list re-exports it unchanged", () => {
    expect(WebCaseCard).toBe(SharedCaseCard);
    expect(sexLabel("male")).toBe("Male");
    expect(formatDisplayTimestamp("2026-10-23")).toBe("2026-10-23");
  });

  it("keeps the ID at the foot by default and under the title with idBelowTitle", async () => {
    const props = { title: "Ramesh Kumar", caseId: "AAM01-000002", ageYears: 68, sex: "male", dateOfDeath: "2026-09-12", area: "CHC Bhoranj", badges: [{ label: "Draft" }], actions: <button data-label="Resume" /> };
    await render(<SharedCaseCard {...props} />);
    expect(tree.root.findAllByProps({ testID: "case-id-line" })).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "case-fact-caseId" }).length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
    await render(<SharedCaseCard {...props} idBelowTitle />);
    expect(tree.root.findAllByProps({ testID: "case-id-line" }).length).toBeGreaterThan(0);
    expect(tree.root.findAllByProps({ testID: "case-fact-caseId" })).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "case-fact-age" }).length).toBeGreaterThan(0);
  });
});

describe("Home", () => {
  const items = buildInterviewItems(sources({ drafts: [draft("d1", { death_id: "C1" }), draft("d2")], cases: [caseRow("C1", "Ramesh Kumar"), caseRow("C2", "Sunita Devi"), caseRow("C3", "Mohan Lal")] }));
  const summary = homeSummary(items, interviewCounts(items));
  const base = { loaded: true, offline: false, summary, unsent: 1, canStart: true, canRegister: true, busy: false, onResume: noop, onStart: noop, onRegister: noop, onSend: noop, onViewTodo: noop };

  it("shows the draft count, the name of the latest draft, and unsent and need-a-visit numbers from local data", async () => {
    await render(<HomeView {...base} />);
    const out = text(tree);
    expect(out).toContain("2 drafts in progress");
    expect(out).toContain("Ramesh Kumar");
    expect(labelled(tree, "Resume draft")).toHaveLength(1);
    expect(out).toContain('"1"'); // unsent comes from the shared count, not from drafts
    expect(out).toContain('"2"'); // C2 and C3 still need a visit
    expect(labelled(tree, "Register a death").length).toBeGreaterThan(0);
  });

  it("wires Resume, Send now and View, and hides Register when the account may not register", async () => {
    const calls: string[] = [];
    await render(<HomeView {...base} canRegister={false} onResume={() => calls.push("resume")} onSend={() => calls.push("send")} onViewTodo={() => calls.push("view")} />);
    for (const label of ["Resume draft", "Send now", "View"]) await act(async () => labelled(tree, label)[0].props.onClick());
    expect(calls).toEqual(["resume", "send", "view"]);
    expect(labelled(tree, "Register a death")).toHaveLength(0);
  });

  it("offers Start an interview when no draft is in progress, and the offline notice when offline", async () => {
    const empty = homeSummary([], interviewCounts([]));
    await render(<HomeView {...base} summary={empty} offline />);
    expect(labelled(tree, "Start an interview").length).toBeGreaterThan(0);
    expect(labelled(tree, "Resume draft")).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "state-offline" }).length).toBeGreaterThan(0);
  });

  it("shows skeleton rows, not a spinner, while the local store loads", async () => {
    await render(<HomeView {...base} loaded={false} />);
    expect(tree.root.findAllByProps({ testID: "state-loading" }).length).toBeGreaterThan(0);
  });
});

describe("Interviews", () => {
  const items = buildInterviewItems(sources({
    drafts: [draft("d1", { death_id: "C1" })],
    cases: [caseRow("C1", "Ramesh Kumar"), caseRow("C2", "Sunita Devi")],
    submitted: [{ draft_id: "s1", project_id: "P1", site_id: "S1", death_id: null, va_sid: "v", unique_id: "SENT-1", deceased_name: "Mohan Lal", updated_at: "2026-10-02T00:00:00Z" }],
  }));
  const cards = () => tree.root.findAll((n) => typeof n.type === "string" && String(n.props.testID ?? "").startsWith("interview-"));

  it("shows one card per interview with name, muted ID, badge and exactly one primary action", async () => {
    await render(<InterviewsView {...interviewsProps(items)} />);
    expect(cards()).toHaveLength(3);
    for (const card of cards()) {
      const buttons = card.findAll((n) => n.type === "button");
      expect(buttons).toHaveLength(1);
    }
    expect(labelled(tree, "Resume")).toHaveLength(1);
    expect(labelled(tree, "Start")).toHaveLength(1);
    expect(labelled(tree, "Revise")).toHaveLength(1);
    expect(tree.root.findAllByProps({ testID: "case-id-line" }).length).toBeGreaterThanOrEqual(3);
    expect(text(tree)).toContain("Ramesh Kumar");
  });

  it("filters by chip, with counts on the chips, and by search", async () => {
    await render(<InterviewsView {...interviewsProps(items)} />);
    expect(pressable(tree, "Drafts 1")).toBeDefined();
    expect(pressable(tree, "To do 1")).toBeDefined();
    expect(pressable(tree, "Sent 1")).toBeDefined();
    await act(async () => pressable(tree, "To do 1").props.onPress());
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("Sunita Devi");
    await act(async () => pressable(tree, "All").props.onPress());
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search interviews" }).props.onChangeText("mohan"));
    expect(cards()).toHaveLength(1);
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search interviews" }).props.onChangeText("nobody"));
    expect(cards()).toHaveLength(0);
    expect(text(tree)).toContain("No interviews match your search.");
  });

  it("opens on the chip named by the route", async () => {
    await render(<InterviewsView {...interviewsProps(items)} initialFilter="sent" />);
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("SENT-1");
  });

  it("shows the Empty state with Register a death, Loading skeletons, and Offline with Refresh disabled and the reason", async () => {
    const registered: string[] = [];
    await render(<InterviewsView {...interviewsProps([], { onRegister: () => registered.push("x") })} />);
    expect(text(tree)).toContain("No interviews yet");
    await act(async () => labelled(tree, "Register a death")[0].props.onClick());
    expect(registered).toEqual(["x"]);
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps([], { loaded: false })} />);
    expect(tree.root.findAllByProps({ testID: "state-loading" }).length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps(items, { offline: true })} />);
    expect(tree.root.findAllByProps({ testID: "state-offline" }).length).toBeGreaterThan(0);
    expect(labelled(tree, "Refresh")[0].props.disabled).toBe(true);
    expect(text(tree)).toContain("Refresh needs a connection.");
  });
});

describe("Site picker sheet", () => {
  const target = (siteId: string, siteName: string, unitName: string) => ({
    key: `P1:${siteId}:${unitName}`, label: `${siteName} · ${unitName}`, projectId: "P1", siteId, orgUnitId: `U-${unitName}`, siteName, unitName,
  });
  const targets = [target("S1", "Bhoranj block", "CHC Bhoranj"), target("S1", "Bhoranj block", "PHC Tauni Devi"), target("S2", "Nadaun block", "CHC Nadaun")];

  it("renders nothing while closed", async () => {
    await render(<SitePickerSheet visible={false} targets={targets} onPick={noop} onClose={noop} />);
    expect(tree.toJSON()).toBeNull();
  });

  it("lists unit names under site headers, a Recent row first, and returns the picked target unchanged", async () => {
    const picked: unknown[] = [];
    await render(<SitePickerSheet visible targets={targets} recent={{ siteId: "S1", orgUnitId: "U-PHC Tauni Devi" }} onPick={(t) => picked.push(t)} onClose={noop} />);
    const out = shown(tree);
    expect(out).toContain("Recent");
    expect(out).toContain("Bhoranj block");
    expect(out).toContain("Nadaun block");
    expect(out).not.toContain("Bhoranj block · CHC Bhoranj");
    await act(async () => pressable(tree, "CHC Nadaun").props.onPress());
    expect(picked).toEqual([targets[2]]);
    expect(pressable(tree, "PHC Tauni Devi")).toBeDefined(); // the Recent row and its list row share the label
  });

  it("searches units and says so when nothing matches", async () => {
    await render(<SitePickerSheet visible targets={targets} onPick={noop} onClose={noop} />);
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search units" }).props.onChangeText("nadaun"));
    expect(shown(tree)).toContain("CHC Nadaun");
    expect(shown(tree)).not.toContain("CHC Bhoranj");
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search units" }).props.onChangeText("zzz"));
    expect(shown(tree)).toContain("No unit matches your search.");
  });

  it("falls back to the raw label when every unit is an internal placeholder", async () => {
    await render(<SitePickerSheet visible targets={[target("S1", "Site A", "sites_in_project_P1")]} onPick={noop} onClose={noop} />);
    expect(pressable(tree, "Site A · sites_in_project_P1")).toBeDefined();
  });
});

describe("StateView", () => {
  it("renders empty and error variants with an optional action", async () => {
    const pressed: string[] = [];
    await render(<StateView title="No interviews yet" hint="Register a death to begin." actionLabel="Go" onAction={() => pressed.push("go")} />);
    expect(tree.root.findAllByProps({ testID: "state-empty" }).length).toBeGreaterThan(0);
    await act(async () => labelled(tree, "Go")[0].props.onClick());
    expect(pressed).toEqual(["go"]);
    await act(async () => tree.unmount());
    await render(<StateView kind="error" title="Could not load" />);
    expect(tree.root.findAllByProps({ testID: "state-error" }).length).toBeGreaterThan(0);
    expect(labelled(tree, "Go")).toHaveLength(0);
  });

  it("renders the requested number of skeleton rows and the persistent offline notice", async () => {
    await render(<SkeletonCards count={4} />);
    expect(tree.root.findAll((n) => typeof n.type === "string" && n.props.importantForAccessibility === "no-hide-descendants")).toHaveLength(4);
    await act(async () => tree.unmount());
    await render(<OfflineNotice />);
    expect(text(tree)).toContain("You are offline. Work is saved on this phone and sent later.");
  });
});
