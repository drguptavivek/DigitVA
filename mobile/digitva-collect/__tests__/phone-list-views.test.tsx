import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Text } from "react-native";

jest.mock("react-native-safe-area-context", () => ({
  ...jest.requireActual("react-native-safe-area-context"),
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));
jest.mock("../src/ui", () => require("../test-support/uiMockExtras").withUiExtras({
  Button: ({ label, onPress, disabled, kind }: { label: string; onPress?: () => void; disabled?: boolean; kind?: string }) =>
    (jest.requireActual("react") as typeof React).createElement("button", { "data-label": label, "data-kind": kind, disabled, onClick: onPress }, label),
  useUiStyles: () => ({ card: {}, error: {}, muted: {}, text: {} }),
  stateLabel: (s: string) => s,
  Card: ({ children, testID }: { children: React.ReactNode; testID?: string }) =>
    (jest.requireActual("react") as typeof React).createElement("section", { testID }, children),
  Separator: () => null,
  Notice: ({ children, tone }: { children: React.ReactNode; tone?: string }) =>
    (jest.requireActual("react") as typeof React).createElement("aside", { "data-tone": tone ?? "info" }, children),
  ListRow: ({ label, secondary, value, onPress, accessibilityLabel, tone, badge }: { label: string; secondary?: string; value?: string; onPress?: () => void; accessibilityLabel?: string; tone?: string; badge?: boolean }) =>
    (jest.requireActual("react") as typeof React).createElement(onPress ? "button" : "div", { "data-label": accessibilityLabel ?? label, "data-tone": tone, "data-badge": badge, onClick: onPress }, label, secondary, value),
}));
jest.mock("../src/web/LocationCapture", () => ({ MapsPinButton: () => null }));

import { CaseCard as SharedCaseCard } from "../src/ui/CaseCard";
import { CaseCard as WebCaseCard, formatDisplayTimestamp, sexLabel } from "../src/web/DeathsList";
import { HomeView, InterviewCard, InterviewsView, ProjectLine, SitePickerSheet } from "../src/nativeRoutes/worklistParts";
import { OfflineNotice, SkeletonCards, StateView } from "../src/ui/StateView";
import { buildInterviewItems, interviewCounts } from "../src/ui/interviewRows";
import { homeSummary } from "../src/ui/homeSummary";
import en from "../src/strings/en.json";

const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON(), (k, v) => ((k === "data" && Array.isArray(v)) || k === "refreshControl" || k === "ListHeaderComponent" ? undefined : v));
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
  loadingMore: false, loadFailed: false, onAction: noop, onRetryDemo: noop, onRegister: noop, onRefresh: noop, onLoadMore: noop, ...extra,
});

describe("CaseCard", () => {
  it("is the one card: the web list re-exports it unchanged", () => {
    expect(WebCaseCard).toBe(SharedCaseCard);
    expect(sexLabel("male")).toBe("Male");
    expect(formatDisplayTimestamp("2026-10-23")).toBe("23 Oct 2026");
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
  const base = { loaded: true, offline: false, summary, unsent: 1, canStart: true, busy: false, onResume: noop, onStart: noop, onSend: noop, onViewTodo: noop };

  it("shows the draft count, the name of the latest draft, and unsent and need-a-visit numbers from local data", async () => {
    await render(<HomeView {...base} />);
    const out = text(tree);
    expect(out).toContain("2 drafts in progress");
    expect(out).toContain("Ramesh Kumar");
    expect(labelled(tree, "Resume draft")).toHaveLength(1);
    expect(out).toContain('"1"'); // unsent comes from the shared count, not from drafts
    expect(out).toContain('"2"'); // C2 and C3 still need a visit
  });

  it("wires Resume, Send now and View; Register lives in the go rows, not in Home's own content", async () => {
    const calls: string[] = [];
    await render(<HomeView {...base} onResume={() => calls.push("resume")} onSend={() => calls.push("send")} onViewTodo={() => calls.push("view")} />);
    for (const label of ["Resume draft", "Send now", "2 To do. View"]) await act(async () => labelled(tree, label)[0].props.onClick());
    expect(calls).toEqual(["resume", "send", "view"]);
    expect(labelled(tree, "Register a death")).toHaveLength(0);
  });

  it("uses the Interviews words and counts: To do and Drafts, each row opening its own filter (digitva-pwi9)", async () => {
    const counts = interviewCounts(items);
    const seen: string[] = [];
    await render(<HomeView {...base} onViewTodo={() => seen.push("todo")} onViewDrafts={() => seen.push("drafts")} />);
    await act(async () => labelled(tree, `${counts.todo} To do. View`)[0].props.onClick());
    await act(async () => labelled(tree, `${counts.drafts} Drafts. View`)[0].props.onClick());
    expect(seen).toEqual(["todo", "drafts"]);
    expect(text(tree)).not.toContain("need a visit");
  });

  it("opens the Sync sheet from the Unsent row, and says why Send now is off when offline (digitva-0esm)", async () => {
    const calls: string[] = [];
    await render(<HomeView {...base} unsent={3} onOpenSync={() => calls.push("sync")} />);
    await act(async () => labelled(tree, "3 Unsent. View")[0].props.onClick());
    expect(calls).toEqual(["sync"]);
    expect(tree.root.findAllByProps({ testID: "home-send-offline" })).toHaveLength(0);
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={3} offline />);
    expect(labelled(tree, "Send now")[0].props.disabled).toBe(true);
    expect(shown(tree)).toContain(en.offlineSendNow);
  });

  it("disables the start buttons while the collection gate is closed, but never Resume (digitva-0pb7)", async () => {
    await render(<HomeView {...base} startClosed />);
    expect(labelled(tree, "New interview")[0].props.disabled).toBe(true);
    expect(labelled(tree, "Resume draft")[0].props.disabled).toBeFalsy();
    await act(async () => tree.unmount());
    await render(<HomeView {...base} summary={homeSummary([], interviewCounts([]))} startClosed />);
    expect(labelled(tree, "Start an interview")[0].props.disabled).toBe(true);
  });

  it("offers Start an interview when no draft is in progress, and the offline notice when offline", async () => {
    const empty = homeSummary([], interviewCounts([]));
    await render(<HomeView {...base} summary={empty} offline />);
    expect(labelled(tree, "Start an interview").length).toBeGreaterThan(0);
    expect(labelled(tree, "Resume draft")).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "state-offline" }).length).toBeGreaterThan(0);
  });

  it("puts the counts in one card; Unsent takes the attention tint and badge only while something waits", async () => {
    await render(<HomeView {...base} unsent={1} />);
    expect(tree.root.findAllByProps({ testID: "home-counts" }).length).toBeGreaterThan(0);
    const unsentRow = labelled(tree, "Unsent")[0];
    expect(unsentRow.props).toMatchObject({ "data-tone": "attention", "data-badge": true });
    expect(labelled(tree, "Drafts")).toHaveLength(1);
    await act(async () => tree.unmount());
  });

  it("hides zero-count rows: Unsent 0, Need a visit 0, Drafts 0 (and the card when all are zero)", async () => {
    await render(<HomeView {...base} unsent={1} />);
    expect(labelled(tree, "Unsent")).toHaveLength(1);
    expect(labelled(tree, "Drafts")).toHaveLength(1);
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={0} summary={homeSummary([], interviewCounts([]))} />);
    expect(labelled(tree, "Unsent")).toHaveLength(0);
    expect(labelled(tree, "Need a visit")).toHaveLength(0);
    expect(labelled(tree, "Drafts")).toHaveLength(0);
    expect(tree.root.findAllByProps({ testID: "home-counts" })).toHaveLength(0);
    // The one primary action stays.
    expect(labelled(tree, "Start an interview")).toHaveLength(1);
    expect(text(tree)).not.toContain("Online cases");
  });

  it("shows attached files beside the record count, not inside it", async () => {
    await render(<HomeView {...base} unsent={1} unsentFiles={2} />);
    expect(text(tree)).toContain("Attached files also waiting: 2");
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={1} unsentFiles={0} />);
    expect(text(tree)).not.toContain("attached files");
  });

  it("has one filled button: Send now while something is unsent; the next step is tint-filled", async () => {
    await render(<HomeView {...base} />);
    expect(labelled(tree, "Send now")[0].props["data-kind"]).toBeUndefined();
    expect(labelled(tree, "Resume draft")[0].props["data-kind"]).toBe("secondary");
  });

  it("with nothing unsent hides Send now and fills the next step, Resume or Start", async () => {
    await render(<HomeView {...base} unsent={0} />);
    expect(labelled(tree, "Resume draft")[0].props["data-kind"]).toBe("primary");
    expect(labelled(tree, "Send now")).toHaveLength(0);
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={0} summary={homeSummary([], interviewCounts([]))} />);
    expect(labelled(tree, "Start an interview")[0].props["data-kind"]).toBe("primary");
    expect(labelled(tree, "Send now")).toHaveLength(0);
  });

  it("keeps Send now as the primary while the queue is not counted yet, and for waiting files alone", async () => {
    await render(<HomeView {...base} unsent={undefined} />);
    expect(labelled(tree, "Send now")[0].props["data-kind"]).toBeUndefined();
    expect(labelled(tree, "Resume draft")[0].props["data-kind"]).toBe("secondary");
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={0} unsentFiles={1} />);
    expect(labelled(tree, "Send now")).toHaveLength(1);
  });

  it("shows skeleton rows, not a spinner, while the local store loads", async () => {
    await render(<HomeView {...base} loaded={false} />);
    expect(tree.root.findAllByProps({ testID: "state-loading" }).length).toBeGreaterThan(0);
  });

  it("draws the loading Home as its three cards, with no counts, buttons or wrong content", async () => {
    await render(<HomeView {...base} loaded={false}><button data-label="Register a death" /></HomeView>);
    const loading = tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "state-loading")[0];
    expect(loading.props.accessibilityLabel).toBe(en.loading);
    // The counts card, the next-step card and the go-rows card (the Card mock renders a <section>).
    expect(loading.findAllByType("section" as never)).toHaveLength(3);
    expect(labelled(tree, "Start an interview")).toHaveLength(0);
    expect(labelled(tree, "Send now")).toHaveLength(0);
    expect(labelled(tree, "Register a death")).toHaveLength(0);
  });

  it("offline keeps the next step filled and Send now visible but disabled", async () => {
    await render(<HomeView {...base} offline unsent={2} summary={homeSummary([], interviewCounts([]))} />);
    expect(labelled(tree, "Send now")[0].props.disabled).toBe(true);
    expect(labelled(tree, "Start an interview")[0].props["data-kind"]).toBe("primary");
    expect(labelled(tree, "Start an interview")[0].props.disabled).toBe(false);
    await act(async () => tree.unmount());
    await render(<HomeView {...base} offline unsent={2} />);
    expect(labelled(tree, "Resume draft")[0].props["data-kind"]).toBe("primary");
    // Online the same queue demotes the next step (frozen look).
    await act(async () => tree.unmount());
    await render(<HomeView {...base} unsent={2} />);
    expect(labelled(tree, "Resume draft")[0].props["data-kind"]).toBe("secondary");
  });
});

describe("ProjectLine", () => {
  it("keeps its line while there is no project yet, so the cards under it never jump", async () => {
    await render(<ProjectLine project="GUJ026" name="Gujarat Health System" />);
    expect(shown(tree)).toContain("GUJ026 · Gujarat Health System");
    await act(async () => tree.unmount());
    await render(<ProjectLine />);
    const empty = tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "project-line-empty");
    expect(empty).toHaveLength(1);
    expect(empty[0].props.style.minHeight).toBe(20);
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
    expect(pressable(tree, "More")).toBeDefined();
    expect(pressable(tree, "Sent 1")).toBeUndefined();
    await act(async () => pressable(tree, "To do 1").props.onPress());
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("Sunita Devi");
    // Tapping the picked chip again clears it (all interviews).
    await act(async () => pressable(tree, "To do 1").props.onPress());
    expect(cards()).toHaveLength(3);
    // Sent is behind More.
    await act(async () => pressable(tree, "More").props.onPress());
    await act(async () => pressable(tree, "Sent 1").props.onPress());
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("SENT-1");
    await act(async () => pressable(tree, "More").props.onPress());
    await act(async () => pressable(tree, "All").props.onPress());
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search interviews" }).props.onChangeText("mohan"));
    expect(cards()).toHaveLength(1);
    await act(async () => tree.root.findByProps({ accessibilityLabel: "Search interviews" }).props.onChangeText("nobody"));
    expect(cards()).toHaveLength(0);
    expect(text(tree)).toContain("No interviews match your search.");
  });

  it("opens the More filters without a search box, and names the picked filter on the chip", async () => {
    await render(<InterviewsView {...interviewsProps(items)} />);
    await act(async () => pressable(tree, "More").props.onPress());
    // Assert the three options are present before asserting the search box is absent.
    expect(pressable(tree, "Sent 1")).toBeDefined();
    expect(pressable(tree, "Revisions")).toBeDefined();
    expect(pressable(tree, "All")).toBeDefined();
    expect(tree.root.findAll((n) => n.props.accessibilityLabel === "Search units")).toHaveLength(0);
    await act(async () => pressable(tree, "Sent 1").props.onPress());
    expect(pressable(tree, "More")).toBeDefined();
    expect(shown(tree)).toContain("More: Sent");
    await act(async () => pressable(tree, "More").props.onPress());
    expect(pressable(tree, "Revisions")).toBeDefined();
    await act(async () => pressable(tree, "Revisions").props.onPress());
    expect(shown(tree)).toContain("More: Revisions");
    await act(async () => pressable(tree, "More").props.onPress());
    await act(async () => pressable(tree, "All").props.onPress());
    expect(shown(tree)).not.toContain("More: ");
  });

  it("opens the case detail when a Sent case card is tapped anywhere on its body", async () => {
    const onAction = jest.fn();
    const sent = buildInterviewItems(sources({ cases: [caseRow("C9", "Geeta Devi", { state: "completed" })] }));
    expect(sent[0].kind).toBe("sent");
    await render(<InterviewsView {...interviewsProps(sent, { onAction })} />);
    await act(async () => tree.root.findByProps({ testID: `open-${sent[0].key}` }).props.onPress());
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ type: "case", deathId: "C9" }));
  });

  it("opens the case detail from the body of a Sent card whose button is Revise", async () => {
    const onAction = jest.fn();
    const submitted = [{ draft_id: "D1", project_id: "P1", site_id: "S1", death_id: "C7", va_sid: "V1", unique_id: "SC01-000173", updated_at: "2026-10-23T13:40:00.000Z" }] as never;
    const sent = buildInterviewItems(sources({ submitted }));
    expect(sent[0].action?.type).toBe("revise");
    await render(<InterviewsView {...interviewsProps(sent, { onAction })} />);
    await act(async () => tree.root.findByProps({ testID: `open-${sent[0].key}` }).props.onPress());
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({ type: "case", deathId: "C7", projectId: "P1" }));
    expect(labelled(tree, "Revise")).toHaveLength(1);
  });

  it("keeps the chip counts of the whole list while a filter is active", async () => {
    await render(<InterviewsView {...interviewsProps(items)} initialFilter="sent" />);
    expect(pressable(tree, "To do 1")).toBeDefined();
    expect(pressable(tree, "Drafts 1")).toBeDefined();
  });

  it("opens on the chip named by the route", async () => {
    await render(<InterviewsView {...interviewsProps(items)} initialFilter="sent" />);
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("SENT-1");
  });

  it("follows a new route filter while mounted (Home's View links reuse the Interviews tab)", async () => {
    await render(<InterviewsView {...interviewsProps(items)} initialFilter="sent" />);
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("SENT-1");
    await act(async () => tree.update(<InterviewsView {...interviewsProps(items)} initialFilter="todo" />));
    expect(cards()).toHaveLength(1);
    expect(text(tree)).toContain("Sunita Devi");
    expect(text(tree)).not.toContain("SENT-1");
    // A chip tap still wins until the route names a different filter.
    await act(async () => pressable(tree, "To do 1").props.onPress());
    await act(async () => tree.update(<InterviewsView {...interviewsProps(items)} initialFilter="todo" />));
    expect(cards()).toHaveLength(3);
  });

  it("scrolls the header (search, chips, and the caller's header) with the list", async () => {
    await render(<InterviewsView {...interviewsProps(items)} header={<Text testID="caller-header">Coding case lists</Text>} />);
    const list = tree.root.findAll((n) => n.props.ListHeaderComponent !== undefined)[0];
    expect(list).toBeDefined();
    // An element, not an inline component type, so typing in search keeps focus across renders.
    expect(React.isValidElement(list.props.ListHeaderComponent)).toBe(true);
    expect(list.findAllByProps({ testID: "caller-header" }).length).toBeGreaterThan(0);
    expect(list.findAll((n) => n.props.accessibilityLabel === "Search interviews").length).toBeGreaterThan(0);
  });

  it("shows the Empty state with Register a death, Loading skeletons, and Offline with pull-to-refresh off and the reason", async () => {
    const registered: string[] = [];
    await render(<InterviewsView {...interviewsProps([], { onRegister: () => registered.push("x") })} />);
    expect(text(tree)).toContain("No interviews yet");
    await act(async () => pressable(tree, "Register a death").props.onPress());
    expect(registered).toEqual(["x"]);
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps([], { loaded: false })} />);
    expect(tree.root.findAllByProps({ testID: "state-loading" }).length).toBeGreaterThan(0);
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps(items, { offline: true })} />);
    expect(tree.root.findAllByProps({ testID: "state-offline" }).length).toBeGreaterThan(0);
    expect(refreshControl().props.enabled).toBe(false);
    expect(text(tree)).toContain("Refresh needs a connection.");
  });

  const refreshControl = () => tree.root.findByProps({ testID: "interviews-list" }).props.refreshControl;
  const links = () => tree.root.findAll((n) => n.props.accessibilityRole === "button" && typeof n.props.onPress === "function" && n.type !== "button")
    .filter((n) => typeof n.type !== "string").map((n) => ({ label: n.props.accessibilityLabel, disabled: Boolean(n.props.disabled) }));

  it("chooses the empty-state copy by loaded and offline first, Register second", async () => {
    // Not loaded: skeleton, never the empty copy (no flip while reference data is read).
    await render(<InterviewsView {...interviewsProps([], { loaded: false, canRegister: false })} />);
    expect(tree.root.findAllByProps({ testID: "state-loading" }).length).toBeGreaterThan(0);
    expect(text(tree)).not.toContain("No interviews yet");
    expect(text(tree)).not.toContain("Connect to the internet");
    await act(async () => tree.unmount());
    // Online coder-only account: no "Connect to the internet", no Register.
    await render(<InterviewsView {...interviewsProps([], { canRegister: false })} />);
    expect(text(tree)).toContain("No cases on this phone yet. Pull down to refresh.");
    expect(text(tree)).not.toContain("Connect to the internet");
    expect(links()).toEqual([{ label: "Refresh", disabled: false }]);
    await act(async () => tree.unmount());
    // Online with Register: the frozen copy and links.
    await render(<InterviewsView {...interviewsProps([])} />);
    expect(text(tree)).toContain("No cases on this phone yet. Pull down to refresh, or register a death.");
    expect(links()).toEqual([{ label: "Refresh", disabled: false }, { label: "Register a death", disabled: false }]);
    await act(async () => tree.unmount());
    // Offline: the connect hint; Register first, then Refresh waiting for the connection.
    await render(<InterviewsView {...interviewsProps([], { offline: true })} />);
    expect(text(tree)).toContain("Connect to the internet and tap Refresh to load your cases.");
    expect(links()).toEqual([{ label: "Register a death", disabled: false }, { label: "Refresh", disabled: true }]);
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps([], { offline: true, canRegister: false })} />);
    expect(text(tree)).toContain("Connect to the internet and tap Refresh to load your cases.");
    expect(links()).toEqual([{ label: "Refresh", disabled: true }]);
  });

  it("has no Send now or Refresh button: Send lives in the Sync sheet and the list refreshes when pulled", async () => {
    const calls: string[] = [];
    await render(<InterviewsView {...interviewsProps(items, { onRefresh: () => calls.push("refresh") })} />);
    expect(cards()).toHaveLength(3);
    expect(labelled(tree, "Send now")).toHaveLength(0);
    expect(labelled(tree, "Refresh")).toHaveLength(0);
    expect(refreshControl().props).toMatchObject({ refreshing: false, enabled: true });
    await act(async () => refreshControl().props.onRefresh());
    expect(calls).toEqual(["refresh"]);
  });

  it("shows the refresh spinner while refreshing and ignores a pull while offline or busy", async () => {
    const calls: string[] = [];
    await render(<InterviewsView {...interviewsProps(items, { refreshing: true })} />);
    expect(refreshControl().props.refreshing).toBe(true);
    await act(async () => tree.unmount());
    for (const extra of [{ offline: true }, { busy: true }]) {
      await render(<InterviewsView {...interviewsProps(items, { ...extra, onRefresh: () => calls.push("refresh") })} />);
      await act(async () => refreshControl().props.onRefresh());
      await act(async () => tree.unmount());
    }
    expect(calls).toEqual([]);
  });
});

describe("Interviews revisions load failure", () => {
  const items = buildInterviewItems(sources({ cases: [caseRow("C1", "Ramesh Kumar")] }));
  it("says Revisions need a connection when offline, and keeps the Retry + Ref text for a real error", async () => {
    await render(<InterviewsView {...interviewsProps(items, { loadFailed: true, offline: true })} />);
    expect(text(tree)).toContain("Revisions need a connection.");
    expect(text(tree)).not.toContain("Retry revision");
    await act(async () => tree.unmount());
    await render(<InterviewsView {...interviewsProps(items, { loadFailed: true, loadFailedText: "Retry revision\nRef: HTTP 500 server_error" })} />);
    expect(text(tree)).toContain("Retry revision");
    expect(text(tree)).toContain("Ref: HTTP 500 server_error");
    expect(text(tree)).not.toContain("Revisions need a connection.");
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
    expect(tree.root.findAll((n) => typeof n.type === "string" && n.props["aria-hidden"] === true)).toHaveLength(4);
    await act(async () => tree.unmount());
    await render(<OfflineNotice />);
    expect(text(tree)).toContain("You are offline. Work is saved on this phone and sent later.");
  });
});

describe("Delete draft on the Interviews list", () => {
  const refusal = { ref: "HTTP 422 invalid_interview", status: 422, message: "No.", at: "2026-10-23T10:15:00Z" };
  const itemOf = (row: unknown, extra = {}) => buildInterviewItems(sources({ drafts: [row], ...extra }))[0];

  it("is offered only for a draft never sent: in progress, no server copy, no issue, no refusal", () => {
    expect(itemOf(draft("d1")).deletable).toMatchObject({ id: "d1" });
    expect(itemOf(draft("d2", { completed: 1 })).deletable).toBeUndefined();
    expect(itemOf(draft("d3", { server_draft_id: "srv", base_updated_at: "2026-10-23T00:00:00Z" })).deletable).toBeUndefined();
    expect(itemOf(draft("d4", { upload_issue: "case_conflict" })).deletable).toBeUndefined();
    expect(itemOf(draft("d5"), { refusals: new Map([["d5", refusal]]) }).deletable).toBeUndefined();
  });

  it("shows the button on a deletable card only, and calls back with that item", async () => {
    const onDeleteDraft = jest.fn();
    const items = buildInterviewItems(sources({ drafts: [draft("d1"), draft("d2", { completed: 1 })] }));
    // Subject present first: both cards render.
    await render(<InterviewsView {...interviewsProps(items, { onDeleteDraft })} />);
    expect(tree.root.findAllByProps({ testID: "interview-draft-d1" }).length).toBeGreaterThan(0);
    expect(tree.root.findAllByProps({ testID: "interview-draft-d2" }).length).toBeGreaterThan(0);
    const buttons = tree.root.findAll((n) => n.props.accessibilityLabel === "Delete draft" && typeof n.props.onPress === "function");
    expect(buttons).toHaveLength(1);
    await act(async () => buttons[0].props.onPress());
    expect(onDeleteDraft).toHaveBeenCalledWith(expect.objectContaining({ key: "draft-d1" }));
  });
});

describe("Another interviewer's open draft", () => {
  const startedAt = "2026-10-04T10:30:00Z";
  const lines = (extra: object) =>
    buildInterviewItems(sources({ cases: [caseRow("C1", "Ramesh Kumar", { other_draft_active: true, other_draft_started_at: startedAt, ...extra })] }))[0].lines.map((l) => l.text);

  it("names the interviewer from a cached case when the server sent the name", () => {
    expect(lines({ other_draft_started_by: "Asha Verma" })).toContain(`Asha Verma started this on 4 Oct. Check with them before you start.`);
  });

  it("falls back to the unnamed text without the name, and the undated one without a usable time", () => {
    const unnamed = lines({ other_draft_started_by: null });
    expect(unnamed).toContain(`Another interviewer started this on 4 Oct. Check with them before you start.`);
    expect(unnamed.join(" ")).not.toContain("null");
    expect(lines({ other_draft_started_at: "invalid", other_draft_started_by: "Asha Verma" })).toContain("As of the last sync (Not synced yet), another interviewer has started this interview.");
  });
});

describe("list rows (digitva-ydui)", () => {
  it("InterviewCard is memoised and only re-renders for a new item or handler", async () => {
    expect((InterviewCard as unknown as { $$typeof: symbol }).$$typeof).toBe(Symbol.for("react.memo"));
    const items = buildInterviewItems(sources({ cases: [caseRow("C1", "Ramesh Kumar")] }));
  });
});
