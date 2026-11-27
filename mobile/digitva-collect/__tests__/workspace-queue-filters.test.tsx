/**
 * The Code and Review queues' Sort and filter (owner 2026-11-27): every choice is a server parameter, the screen
 * cache keys on all of them, the panel offers only what the shown list accepts, and the phone's quick chips toggle
 * sex and age group. docs/policy/case-list-views.md "Code and Review queue sort and filter".
 */
import React from "react";
import { AppState, Platform } from "react-native";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";

import type { AccessProject } from "../src/api";
import { ProjectSelect } from "../src/ui/ProjectSelect";
import { Select } from "../src/ui/Select";
import { clearScreenCache, readCached, screenKey } from "../src/web/screenCache";
import { createWorkspaceApi, type QueuePageOptions, type WorkspaceApi } from "../src/workspace/api";
import { DateField } from "../src/workspace/doris/DateField";
import { QueueScreen } from "../src/workspace/QueueScreen";

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");

const row = {
  va_sid: "sid-1", va_uniqueid_masked: "UID-1", va_form_id: "F", project_id: "P1", site_id: "S1",
  va_submission_date: "2026-10-01", va_data_collector: null, va_deceased_age: 52, va_deceased_gender: "female", va_narration_language: "english",
};
const page = (key: "forms" | "history" | "cases", total = 14) => jest.fn((options?: QueuePageOptions) => Promise.resolve({
  [key]: key === "history" ? [{ ...row, va_coding_date: "2026-10-02", va_code_status: "Coded", recodeable: false, va_reviewed_at: "2026-10-02T00:00:00+00:00" }] : [row],
  count: 1, limit: options?.limit ?? 50, offset: options?.offset ?? 0, has_more: true,
  // The filtered size: any filter narrows 14 to 3.
  total: Object.keys(options ?? {}).some((k) => !["projectId", "siteId", "orgUnitId", "limit", "offset"].includes(k) && (options as Record<string, unknown>)[k] !== undefined) ? 3 : total,
}));

function makeApi(overrides: Partial<WorkspaceApi> = {}, languages: string[] | null = ["english", "hindi"]): WorkspaceApi {
  const lang = languages ? { languages: { mine: languages } } : {};
  return {
    getCodingStats: jest.fn().mockResolvedValue({ random_ready: 2, pick_ready: 14, completed: 1, has_random_mode: true, has_pick_mode: true, ...lang }),
    getCodingProjects: jest.fn().mockResolvedValue({ projects: ["P1", "P2"], project_options: [{ project_id: "P1", project_name: "Project One" }, { project_id: "P2", project_name: "Project Two" }], last_project_id: null }),
    getReviewerProjects: jest.fn().mockResolvedValue({ project_options: [{ project_id: "P1", project_name: "Project One" }], last_project_id: null }),
    getCodingAllocation: jest.fn().mockResolvedValue(null),
    getReviewerStats: jest.fn().mockResolvedValue({ in_scope: 3, completed: 1, available: 2, allocation: null, ...lang }),
    getReviewerAllocation: jest.fn().mockResolvedValue(null),
    getCodingAvailable: page("forms"),
    getCodingHistory: page("history"),
    getReviewerAvailable: page("cases"),
    getReviewerHistory: page("history"),
    getWorkspace: jest.fn(),
    ...overrides,
  } as unknown as WorkspaceApi;
}

const access = (piiVisible: boolean) => [{
  project_id: "P1", project_name: "Project One", has_tree: false, pii_visible: piiVisible,
  sites: [{ site_id: "S1", site_name: "Site One", roles: [] }], units: [],
  actions: { code: { project: true, site_ids: [], org_unit_ids: [] }, review: { project: true, site_ids: [], org_unit_ids: [] } },
}] as unknown as AccessProject[];

async function settle() {
  for (let i = 0; i < 3; i += 1) await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

async function wait(ms: number) {
  await act(async () => { await new Promise((done) => setTimeout(done, ms)); });
  await settle();
}

async function mount(element: React.ReactElement) {
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(element); });
  await settle();
  return renderer;
}

const pressable = (root: ReactTestInstance, label: string) =>
  root.findAll((n) => typeof n.props.onPress === "function" && n.props.accessibilityLabel === label)[0];

async function press(renderer: ReactTestRenderer, label: string) {
  const target = pressable(renderer.root, label);
  expect(target).toBeDefined();
  await act(async () => { target.props.onPress(); });
  await settle();
}

const filtersButton = (renderer: ReactTestRenderer) => renderer.root.findAll((n) => n.props.testID === "queue-filters" && typeof n.props.onPress === "function")[0];

async function openPanel(renderer: ReactTestRenderer) {
  await act(async () => { filtersButton(renderer).props.onPress(); });
  await settle();
}

async function show(renderer: ReactTestRenderer) {
  const target = renderer.root.findAll((n) => typeof n.props.onPress === "function" && /^Show (\d+ )?cases$/.test(String(n.props.accessibilityLabel ?? "")))[0];
  expect(target).toBeDefined();
  await act(async () => { target.props.onPress(); });
  await settle();
}

const headers = (renderer: ReactTestRenderer) => renderer.root.findAll((n) => (n.type as unknown) === "Text" && n.props.accessibilityRole === "header")
  .map((n) => n.children.join(""));
const text = (renderer: ReactTestRenderer) => JSON.stringify(renderer.toJSON());
const lastCall = (fn: unknown) => (fn as jest.Mock).mock.calls.at(-1)?.[0];

function web() {
  Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
}

afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
  clearScreenCache();
});

describe("queue filter URL", () => {
  function capture() {
    const paths: string[] = [];
    const api = createWorkspaceApi(async (path) => {
      paths.push(path);
      const key = path.includes("/available") ? (path.includes("/coding/") ? "forms" : "cases") : "history";
      const url = new URL(path, "http://x");
      return { [key]: [], count: 0, limit: Number(url.searchParams.get("limit")), offset: Number(url.searchParams.get("offset")), has_more: false, total: 7 };
    });
    return { api, paths };
  }

  test("each filter maps to its parameter, repeatables repeat, and the total is read", async () => {
    const { api, paths } = capture();
    const reply = await api.getCodingHistory({
      projectId: "P1", siteId: "S1", sort: "age_desc", state: ["coded", "not_codeable"], sex: "male", ageGroup: ["neonate", "adult"],
      language: ["en", "hi"], interviewedFrom: "2026-11-01", interviewedTo: "2026-11-27", interviewer: "Anita", q: "0002", limit: 50, offset: 100,
    });
    const params = new URL(paths[0], "http://x").searchParams;
    expect(new URL(paths[0], "http://x").pathname).toBe("/api/v1/coding/history");
    expect(params.get("project_id")).toBe("P1");
    expect(params.get("site_id")).toBe("S1");
    expect(params.get("sort")).toBe("age_desc");
    expect(params.getAll("state")).toEqual(["coded", "not_codeable"]);
    expect(params.get("sex")).toBe("male");
    expect(params.getAll("age_group")).toEqual(["neonate", "adult"]);
    expect(params.getAll("language")).toEqual(["en", "hi"]);
    expect(params.get("interviewed_from")).toBe("2026-11-01");
    expect(params.get("interviewed_to")).toBe("2026-11-27");
    expect(params.get("interviewer")).toBe("Anita");
    expect(params.get("q")).toBe("0002");
    expect(params.get("offset")).toBe("100");
    expect(reply.total).toBe(7);
  });

  test("recodeable is sent as recodeable=1 only when set", async () => {
    const { api, paths } = capture();
    await api.getCodingHistory({ recodeable: "1", limit: 50, offset: 0 });
    await api.getCodingHistory({ limit: 50, offset: 0 });
    expect(new URL(paths[0], "http://x").searchParams.get("recodeable")).toBe("1");
    expect(new URL(paths[1], "http://x").searchParams.has("recodeable")).toBe(false);
  });

  test("absent or empty filters send nothing", async () => {
    const { api, paths } = capture();
    await api.getReviewerAvailable({ state: [], ageGroup: [], language: [], interviewer: "", q: "" });
    expect(paths[0]).toBe("/api/v1/reviewing/available?limit=50&offset=0");
  });

  test("a missing or malformed total is left out, never a refusal of the page", async () => {
    for (const total of [undefined, -1, 1.5, "7"]) {
      const api = createWorkspaceApi(async () => ({ forms: [], count: 0, limit: 50, offset: 0, has_more: false, ...(total === undefined ? {} : { total }) }));
      expect(await api.getCodingAvailable()).not.toHaveProperty("total");
    }
  });
});

describe("queue Sort and filter panel", () => {
  test("filters go to the server, the page starts again at offset 0, and the result line says N of the unfiltered total", async () => {
    web();
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />);
    expect(text(renderer)).toContain("14 cases");
    await press(renderer, "Next");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 50 });
    await openPanel(renderer);
    await press(renderer, "Filter sex: Female");
    await press(renderer, "Age group: Neonate (under 28 d)");
    await press(renderer, "Interviewed: oldest first");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, sort: "interviewed_asc", sex: "female", ageGroup: ["neonate"], limit: 50, offset: 0 });
    // The unfiltered size of the same list, one row, for "3 of 14".
    expect(api.getCodingAvailable).toHaveBeenCalledWith({ projectId: undefined, limit: 1, offset: 0 });
    expect(text(renderer)).toContain("3 of 14 cases");
    expect(text(renderer)).toContain("Sort: Interviewed, oldest");
    await act(async () => { renderer.unmount(); });
  });

  test("Show N cases counts the draft on the server, one row, after a pause", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />);
    await openPanel(renderer);
    await press(renderer, "Filter sex: Male");
    expect(pressable(renderer.root, "Show cases")).toBeDefined();
    await wait(350);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, sex: "male", limit: 1, offset: 0 });
    expect(pressable(renderer.root, "Show 3 cases")).toBeDefined();
    await act(async () => { renderer.unmount(); });
  });

  test("the search is sent 300 ms after typing, from page one", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="reviewing" onOpen={jest.fn()} />);
    await press(renderer, "Next");
    const search = renderer.root.findAll((n) => n.props.accessibilityLabel === "Search cases" && typeof n.props.onChangeText === "function")[0];
    await act(async () => { search.props.onChangeText(" 0002 "); });
    expect(lastCall(api.getReviewerAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 50 });
    await wait(350);
    expect(lastCall(api.getReviewerAvailable)).toEqual({ projectId: undefined, q: "0002", limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });
  });

  test("Workflow state is offered only on lists with states, and a tab that has none never gets one", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />);
    await press(renderer, "My coded cases");
    await openPanel(renderer);
    expect(headers(renderer)).toContain("Workflow state");
    expect(pressable(renderer.root, "Workflow state: Not codeable")).toBeDefined();
    await press(renderer, "Workflow state: Coded");
    await show(renderer);
    expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, state: ["coded"], limit: 50, offset: 0 });
    await press(renderer, "Available");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await openPanel(renderer);
    expect(headers(renderer)).toContain("Sort by");
    expect(headers(renderer)).not.toContain("Workflow state");
    // Back on My coded cases the dropped state does not return.
    await press(renderer, "Close");
    await press(renderer, "My coded cases");
    expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });

    const review = await mount(<QueueScreen api={makeApi()} mode="reviewing" onOpen={jest.fn()} />);
    await openPanel(review);
    expect(pressable(review.root, "Workflow state: Recoded")).toBeDefined();
    expect(pressable(review.root, "Workflow state: Not codeable")).toBeUndefined();
    await press(review, "Close");
    await press(review, "My reviewed cases");
    await openPanel(review);
    expect(headers(review)).not.toContain("Workflow state");
    await act(async () => { review.unmount(); });
  });

  test("the panel's Project is the global setting and clears Site and unit; the badge and chips never count the project", async () => {
    web();
    const api = makeApi();
    const projects = [...access(true), { ...access(true)[0], project_id: "P2", project_name: "Project Two", sites: [{ site_id: "S7", site_name: "Site Seven", roles: [] }] }] as AccessProject[];
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} accessProjects={projects} />);
    await openPanel(renderer);
    const panelProject = () => renderer.root.findAllByType(ProjectSelect).at(-1)!;
    await act(async () => { panelProject().props.onChange(["P1"]); });
    await settle();
    const place = () => renderer.root.findAllByType(Select).find((n) => n.props.label === "Site and unit")!;
    await act(async () => { place().props.onChange("P1:S1"); });
    await press(renderer, "Filter sex: Female");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: "P1", siteId: "S1", sex: "female", limit: 50, offset: 0 });
    // Two filters on (place, sex); the project is neither a chip nor a count.
    expect(filtersButton(renderer).props.accessibilityLabel).toBe("Sort and filter, 2 active");
    expect(text(renderer)).toContain("Filters · 2");
    expect(pressable(renderer.root, "Remove filter: Site One")).toBeDefined();
    expect(renderer.root.findAll((n) => String(n.props.accessibilityLabel).startsWith("Remove filter: Project"))).toHaveLength(0);
    await openPanel(renderer);
    expect(place().props.value).toBe("P1:S1");
    await act(async () => { panelProject().props.onChange(["P2"]); });
    await settle();
    expect(place().props.value).toBe("");
    expect(place().props.options.map((option: { value: string }) => option.value)).toEqual(["", "P2:S7"]);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: "P2", sex: "female", limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });
  });

  test("a chip removes its one filter; Clear all clears everything but the project", async () => {
    web();
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} accessProjects={access(true)} />);
    await openPanel(renderer);
    await act(async () => { renderer.root.findAllByType(ProjectSelect).at(-1)!.props.onChange(["P1"]); });
    await settle();
    await act(async () => { renderer.root.findAllByType(Select).find((n) => n.props.label === "Site and unit")!.props.onChange("P1:S1"); });
    await press(renderer, "Filter sex: Female");
    await press(renderer, "Age group: Neonate (under 28 d)");
    await press(renderer, "Age: oldest first");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: "P1", siteId: "S1", sort: "age_desc", sex: "female", ageGroup: ["neonate"], limit: 50, offset: 0 });
    await press(renderer, "Remove filter: Female");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: "P1", siteId: "S1", sort: "age_desc", ageGroup: ["neonate"], limit: 50, offset: 0 });
    await press(renderer, "Clear all");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: "P1", limit: 50, offset: 0 });
    expect(pressable(renderer.root, "Project: Project One")).toBeDefined();
    await act(async () => { renderer.unmount(); });
  });

  test("Interviewed between sends both dates; a reversed range cannot be shown; Clear dates empties them", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />);
    await openPanel(renderer);
    const dates = () => renderer.root.findAllByType(DateField);
    const setDate = async (index: number, value: string) => { await act(async () => { dates()[index].props.onChange(value); }); };
    expect(dates().map((field) => field.props.label)).toEqual(["Interviewed between From", "Interviewed between To"]);
    await setDate(0, "2026-11-01");
    await setDate(1, "2026-11-27");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, interviewedFrom: "2026-11-01", interviewedTo: "2026-11-27", limit: 50, offset: 0 });
    await openPanel(renderer);
    await setDate(0, "2026-11-28");
    const showButton = () => renderer.root.findAll((n) => typeof n.props.onPress === "function" && /^Show (\d+ )?cases$/.test(String(n.props.accessibilityLabel ?? "")))[0];
    expect(showButton().props.disabled ?? showButton().props.accessibilityState?.disabled).toBe(true);
    await press(renderer, "Clear dates");
    expect(dates().map((field) => field.props.value)).toEqual(["", ""]);
    expect(pressable(renderer.root, "Clear dates")).toBeUndefined();
    expect(showButton().props.disabled ?? showButton().props.accessibilityState?.disabled).toBeFalsy();
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });
  });

  test("phone quick chips toggle sex and age group on the server", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} />);
    // The phone toolbar has no Sort button (sort is in the sheet).
    expect(renderer.root.findAll((n) => n.props.testID === "queue-sort")).toHaveLength(0);
    await press(renderer, "Male");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, sex: "male", limit: 50, offset: 0 });
    await press(renderer, "Female");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, sex: "female", limit: 50, offset: 0 });
    await press(renderer, "Neonate");
    await press(renderer, "Adult");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, sex: "female", ageGroup: ["neonate", "adult"], limit: 50, offset: 0 });
    await press(renderer, "Neonate");
    await press(renderer, "Female");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, ageGroup: ["adult"], limit: 50, offset: 0 });
    expect(filtersButton(renderer).props.accessibilityLabel).toBe("Sort and filter, 1 active");
    expect(text(renderer)).toContain("3 of 14 cases");
    await act(async () => { renderer.unmount(); });
  });

  test("Interviewer is offered on the web for a project with personal-data access only", async () => {
    web();
    const visible = makeApi();
    const shown = await mount(<QueueScreen api={visible} mode="reviewing" onOpen={jest.fn()} accessProjects={access(true)} />);
    await openPanel(shown);
    expect(headers(shown)).toContain("Interviewer");
    const input = shown.root.findAll((n) => n.props.accessibilityLabel === "Interviewer" && typeof n.props.onChangeText === "function")[0];
    await act(async () => { input.props.onChangeText("Anita"); });
    await show(shown);
    expect(lastCall(visible.getReviewerAvailable)).toEqual({ projectId: undefined, interviewer: "Anita", limit: 50, offset: 0 });
    await act(async () => { shown.unmount(); });

    const hidden = await mount(<QueueScreen api={makeApi()} mode="reviewing" onOpen={jest.fn()} accessProjects={access(false)} />);
    await openPanel(hidden);
    expect(headers(hidden)).toContain("Sort by");
    expect(headers(hidden)).not.toContain("Interviewer");
    await act(async () => { hidden.unmount(); });
  });

  test("a user with coding languages gets language chips; one with none gets the message, the editor, and no language sent", async () => {
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} onEditLanguages={jest.fn()} />);
    expect(text(renderer)).toContain("My languages");
    expect(renderer.root.findAll((n) => n.props.testID === "no-languages")).toHaveLength(0);
    await openPanel(renderer);
    // The phone labels it "All mine" (the web "All my languages").
    expect(pressable(renderer.root, "Language: All mine")).toBeDefined();
    await press(renderer, "Language: Hindi");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, language: ["hindi"], limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });

    const edit = jest.fn();
    const none = makeApi({}, []);
    const bare = await mount(<QueueScreen api={none} mode="coding" onOpen={jest.fn()} onEditLanguages={edit} />);
    const line = bare.root.findAll((n) => n.props.testID === "coding-languages")[0];
    expect(JSON.stringify(line.findAll((n) => (n.type as unknown) === "Text").map((n) => n.children))).toContain("No languages configured");
    await press(bare, "Choose languages");
    expect(edit).toHaveBeenCalledTimes(1);
    await openPanel(bare);
    expect(headers(bare)).toContain("Language");
    expect(pressable(bare.root, "Language: All mine")).toBeUndefined();
    await press(bare, "Choose languages");
    expect(edit).toHaveBeenCalledTimes(2);
    for (const [options] of (none.getCodingAvailable as jest.Mock).mock.calls) expect(options).not.toHaveProperty("language");
    await act(async () => { bare.unmount(); });

    // Without an editor the message stands alone.
    const plain = await mount(<QueueScreen api={makeApi({}, [])} mode="reviewing" onOpen={jest.fn()} />);
    expect(text(plain)).toContain("No languages configured");
    expect(pressable(plain.root, "Choose languages")).toBeUndefined();
    await act(async () => { plain.unmount(); });
  });

  test("a chosen language the user no longer has is dropped and never sent", async () => {
    let mine = ["english", "hindi"];
    const api = makeApi({ getCodingStats: jest.fn(() => Promise.resolve({ pick_ready: 14, has_random_mode: false, has_pick_mode: true, languages: { mine } })) as unknown as WorkspaceApi["getCodingStats"] });
    const element = (reloadKey: number) => <QueueScreen api={api} mode="coding" onOpen={jest.fn()} reloadKey={reloadKey} />;
    const renderer = await mount(element(0));
    await openPanel(renderer);
    await press(renderer, "Language: English");
    await show(renderer);
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, language: ["english"], limit: 50, offset: 0 });
    mine = [];
    await act(async () => { renderer.update(element(1)); });
    await settle();
    await settle();
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await act(async () => { renderer.unmount(); });
  });
});

describe("Recodeable only", () => {
  test("offered on My coded cases only; sent, removed by its chip, dropped on Available, part of the page key", async () => {
    web();
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} cacheScope="user-1" />);
    await press(renderer, "History");
    await openPanel(renderer);
    await press(renderer, "Recodeable only");
    await show(renderer);
    expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, recodeable: "1", limit: 50, offset: 0 });
    const key = (filters: string) => screenKey("user-1", "page", "coding", undefined, 0, true, "", filters);
    expect(readCached(key(JSON.stringify({ recodeable: "1" })))).toBeDefined();
    await press(renderer, "Remove filter: Recodeable only");
    expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await openPanel(renderer);
    await press(renderer, "Recodeable only");
    await show(renderer);
    await press(renderer, "Available");
    expect(lastCall(api.getCodingAvailable)).toEqual({ projectId: undefined, limit: 50, offset: 0 });
    await openPanel(renderer);
    expect(pressable(renderer.root, "Recodeable only")).toBeUndefined();
    await act(async () => { renderer.unmount(); });
  });
});

describe("queue screen cache key", () => {
  test("every server filter is part of the page key, so another filter's rows are never seeded", async () => {
    web();
    const api = makeApi();
    const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} cacheScope="user-1" />);
    const key = (filters: string) => screenKey("user-1", "page", "coding", undefined, 0, false, "", filters);
    expect(readCached(key(""))).toBeDefined();
    await openPanel(renderer);
    await press(renderer, "Filter sex: Female");
    await show(renderer);
    const female = key(JSON.stringify({ sex: "female" }));
    expect(female).not.toBe(key(""));
    expect(readCached<{ filters: string; coderAvailable: { total: number } }>(female)?.coderAvailable.total).toBe(3);
    expect(readCached<{ coderAvailable: { total: number } }>(key(""))?.coderAvailable.total).toBe(14);
    // Two different filter sets, two keys.
    await press(renderer, "Remove filter: Female");
    await openPanel(renderer);
    await press(renderer, "Filter sex: Male");
    await show(renderer);
    expect(readCached(key(JSON.stringify({ sex: "male" })))).toBeDefined();
    await act(async () => { renderer.unmount(); });
  });
});

describe("return to the app or tab (digitva-1xof)", () => {
  test("keeps the tab, page and filters and shows the last rows while it reloads", async () => {
    web();
    const listeners: Array<(state: string) => void> = [];
    const spy = jest.spyOn(AppState, "addEventListener").mockImplementation((_type, listener) => {
      listeners.push(listener as (state: string) => void);
      return { remove: jest.fn() } as unknown as ReturnType<typeof AppState.addEventListener>;
    });
    const change = async (state: "active" | "background") => {
      AppState.currentState = state;
      await act(async () => { listeners.forEach((listener) => listener(state)); });
    };
    AppState.currentState = "active";
    try {
      const api = makeApi();
      const renderer = await mount(<QueueScreen api={api} mode="coding" onOpen={jest.fn()} cacheScope="user-1" />);
      await press(renderer, "History");
      await openPanel(renderer);
      await press(renderer, "Filter sex: Female");
      await show(renderer);
      expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, sex: "female", limit: 50, offset: 0 });
      expect(text(renderer)).toContain("UID-1");
      const availableCalls = (api.getCodingAvailable as jest.Mock).mock.calls.length;
      // Every reload call waits (the page and the unfiltered total), so the screen is seen mid-reload.
      const pending: Array<(value: unknown) => void> = [];
      (api.getCodingHistory as jest.Mock).mockImplementation(() => new Promise((resolve) => { pending.push(resolve); }));
      await change("background");
      await change("active");
      // The reload is still out: the last page shows at once, on the same tab and filter.
      expect(text(renderer)).toContain("UID-1");
      expect(lastCall(api.getCodingHistory)).toEqual({ projectId: undefined, sex: "female", limit: 50, offset: 0 });
      expect((api.getCodingAvailable as jest.Mock).mock.calls.length).toBe(availableCalls);
      expect(pressable(renderer.root, "Remove filter: Female")).toBeDefined();
      expect(pending.length).toBeGreaterThan(0);
      await act(async () => { pending.forEach((resolve) => resolve({ history: [], count: 0, limit: 50, offset: 0, has_more: false, total: 0 })); });
      await settle();
      expect(text(renderer)).not.toContain("UID-1");
      await act(async () => { renderer.unmount(); });
    } finally {
      spy.mockRestore();
      AppState.currentState = "active";
    }
  });
});
