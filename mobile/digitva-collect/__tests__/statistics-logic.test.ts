import { activeTab } from "../src/web/navTabs";
import { areaCsvUrl, getAreaProjects, getAreaStaff, getAreaSummary, getStageCounts, listCases } from "../src/area/api";
import { canDrill, countKey, formatDays, formatPercent, hasDeathRegister, pipelineScale, soleOpenUnit, stageWidths } from "../src/web/stats/pipeline";
import { setUiLocale, t } from "../src/i18n";
import {
  allStatuses, areaOptions, casesQuery, chipCount, daysBetween, loadCounts, loadedSummaries, parseView, periodStart, projectsInView, runLimited,
  NO_STAGES, projectStages, stageCountsQuery, toggleProject, viewParams, withTab, type ProjectLoad, type StatsView,
} from "../src/web/stats/view";

const counts = (deaths_reported: number, submitted: number, final_cod: number) => ({ deaths_reported, submitted, final_cod });

describe("pipeline bars", () => {
  test("the scale is the longest stage of any row, so units compare by eye", () => {
    expect(pipelineScale([{ counts: counts(200, 150, 90) }, { counts: counts(50, 240, 10) }])).toBe(240);
    expect(pipelineScale([])).toBe(0);
  });

  test("widths are percent of the scale; a non-zero count is at least 1, zero is 0, none exceed 100", () => {
    expect(stageWidths(counts(200, 100, 50), 200)).toEqual({ reported: 100, interviewed: 50, coded: 25 });
    expect(stageWidths(counts(1, 0, 0), 1000)).toEqual({ reported: 1, interviewed: 0, coded: 0 });
    expect(stageWidths(counts(5, 5, 5), 0)).toEqual({ reported: 0, interviewed: 0, coded: 0 });
    expect(stageWidths(counts(500, 5, 5), 200).reported).toBe(100);
  });

  test("only a unit with units below it opens", () => {
    expect(canDrill({ kind: "unit", has_children: true })).toBe(true);
    expect(canDrill({ kind: "unit", has_children: false })).toBe(false);
    expect(canDrill({ kind: "unrouted", has_children: false })).toBe(false);
    // A sites-mode site opens to its own card, causes and staff.
    expect(canDrill({ kind: "site", has_children: false })).toBe(true);
  });

  test("a project with no death register hides the reported stage and scales on interviews", () => {
    expect(hasDeathRegister([{ deaths_reported: 0 }, { deaths_reported: 0 }])).toBe(false);
    expect(hasDeathRegister([{ deaths_reported: 0 }, { deaths_reported: 3 }])).toBe(true);
    expect(hasDeathRegister([])).toBe(false);
    // Reported is ignored by the scale when it is not shown.
    expect(pipelineScale([{ counts: counts(900, 40, 10) }], false)).toBe(40);
    expect(pipelineScale([{ counts: counts(900, 40, 10) }])).toBe(900);
  });
});

describe("the view from the URL", () => {
  const projects = [{ project_id: "P1", mode: "organization" as const }, { project_id: "S1", mode: "sites" as const }, { project_id: "P2", mode: "organization" as const }];
  const base: StatsView = { tab: "overview", projects: [], period: "all", unit: null, site: null, status: null, overdue: false, source: null };

  test("no project is All; unknown tab, project and period fall back; a comma list and repeats both work", () => {
    expect(parseView({}, projects)).toEqual(base);
    expect(parseView({ tab: "nope", project: "zzz", period: "weekly" }, projects)).toEqual(base);
    expect(parseView({ project: "P1,P2" }, projects)?.projects).toEqual(["P1", "P2"]);
    expect(parseView({ project: ["P2", "P1", "zzz"] }, projects)?.projects).toEqual(["P1", "P2"]);
    // Naming every project is All.
    expect(parseView({ project: "P1,S1,P2" }, projects)?.projects).toEqual([]);
    expect(parseView({}, [])).toBeNull();
  });

  test("an old single-project link keeps its project and unit", () => {
    expect(parseView({ project: "P1", unit: "u1", period: "90d" }, projects)).toEqual({ ...base, projects: ["P1"], unit: "u1", period: "90d" });
  });

  test("unit and site only with exactly one project of the right mode; long values are dropped", () => {
    expect(parseView({ project: "P1,P2", unit: "u1" }, projects)?.unit).toBeNull();
    expect(parseView({ project: "P1", site: "x" }, projects)?.site).toBeNull();
    expect(parseView({ project: "S1", unit: "x", site: "a" }, projects)).toMatchObject({ unit: null, site: "a" });
    expect(parseView({ project: "P1", unit: "u".repeat(65) }, projects)?.unit).toBeNull();
    // A user with one project: All is that project, so its area applies.
    expect(parseView({ unit: "u1" }, [projects[0]])?.unit).toBe("u1");
  });

  test("status, overdue and source are kept only where the tab has them", () => {
    expect(parseView({ tab: "deaths", status: "pending", overdue: "interview", source: "direct" }, projects)).toMatchObject({ status: "pending", overdue: true, source: "direct" });
    expect(parseView({ tab: "deaths", status: "awaiting", overdue: "coding", source: "odk" }, projects)).toMatchObject({ status: null, overdue: false, source: null });
    expect(parseView({ tab: "codings", status: "not_started", overdue: "coding", source: "direct" }, projects)).toMatchObject({ status: "not_started", overdue: true, source: null });
    expect(parseView({ tab: "overview", status: "pending", overdue: "interview" }, projects)).toMatchObject({ status: null, overdue: false });
  });

  test("params leave out defaults and round-trip; a tab change drops the tab's filters", () => {
    expect(viewParams(base)).toEqual({});
    const deaths: StatsView = { ...base, tab: "deaths", projects: ["P1"], period: "12m", unit: "u1", status: "pending", overdue: true, source: "reported" };
    expect(viewParams(deaths)).toEqual({ tab: "deaths", project: "P1", period: "12m", unit: "u1", status: "pending", overdue: "interview", source: "reported" });
    expect(parseView(viewParams(deaths), projects)).toEqual(deaths);
    expect(withTab(deaths, "codings")).toEqual({ ...deaths, tab: "codings", status: null, overdue: false, source: null });
    expect(projectsInView(base, projects)).toEqual(["P1", "S1", "P2"]);
  });

  test("a project checkbox narrows All to one, toggles otherwise, and none or every project is All", () => {
    const all = ["P1", "S1", "P2"];
    expect(toggleProject([], "S1", all)).toEqual(["S1"]);
    expect(toggleProject(["S1"], "P1", all)).toEqual(["P1", "S1"]);
    expect(toggleProject(["S1"], "S1", all)).toEqual([]);
    expect(toggleProject(["P1", "S1"], "P2", all)).toEqual([]);
  });
});

describe("case tables", () => {
  const now = new Date("2026-11-04T10:00:00Z");
  const base: StatsView = { tab: "deaths", projects: [], period: "90d", unit: null, site: null, status: null, overdue: false, source: null };

  test("the period start is a UTC date; all time has none", () => {
    expect(periodStart("30d", now)).toBe("2026-10-05");
    expect(periodStart("12m", now)).toBe("2025-11-04");
    expect(periodStart("all", now)).toBeNull();
  });

  test("Deaths: no status means the preset default; a chip sends its folded statuses; overdue drops the period", () => {
    expect(casesQuery({ ...base, tab: "deaths" }, ["P1", "P2"], now, null)).toEqual({
      preset: "deaths", project_id: "P1,P2", status: null, source: null, reported_from: "2026-08-06", org_unit_id: null, site_id: null, overdue: null, unregistered: "1", interviewed: null, limit: "50", cursor: null,
    });
    expect(casesQuery({ ...base, tab: "deaths", status: "pending", unit: "u1", overdue: true }, ["P1"], now, "c1")).toMatchObject({
      status: "reported,interview_pending,interview_in_progress", reported_from: null, org_unit_id: "u1", overdue: "interview", cursor: "c1",
    });
  });

  test("Interviews and Codings always send statuses (their presets default to work lists), filter on submission and list only interviewed cases", () => {
    expect(casesQuery({ ...base, tab: "interviews" }, ["P1"], now, null)).toMatchObject({
      preset: "interview", status: "submitted_awaiting_coding,in_coding,coded,not_codeable,refused", submitted_from: "2026-08-06", unregistered: "1", interviewed: "1",
    });
    expect(casesQuery({ ...base, tab: "interviews", status: "refused" }, ["P1"], now, null)).toMatchObject({ status: "refused", interviewed: "1" });
    expect(casesQuery({ ...base, tab: "codings", status: "not_started", site: "s1", overdue: true }, ["S1"], now, null)).toMatchObject({
      preset: "coding", status: "submitted_awaiting_coding", submitted_from: null, site_id: "s1", overdue: "coding", unregistered: "1", interviewed: "1",
    });
  });

  test("stage counts ask for the tabs' project, area and period; a project left out has nothing", () => {
    expect(stageCountsQuery(["P1", "P2"], { unit: null, site: null }, "90d", now)).toEqual({
      project_id: "P1,P2", org_unit_id: null, site_id: null, reported_from: "2026-08-06", submitted_from: "2026-08-06",
    });
    expect(stageCountsQuery(["P1"], { unit: "u1", site: null }, "all", now)).toMatchObject({ org_unit_id: "u1", reported_from: null, submitted_from: null });
    const one = { reported: 5, interviewed: 4, coded: 2, overdue_interview: 1, overdue_coding: 0 };
    const reply = { projects: { P1: one }, total: one, thresholds: { interview_days: 60, coding_days: 15 } };
    expect(projectStages(reply, "P1")).toBe(one);
    expect(projectStages(reply, "P2")).toEqual(NO_STAGES);
  });

  test("chip counts fold the server's per-status counts; missing counts are zero", () => {
    const counts = { reported: 2, interview_pending: 3, interview_in_progress: 1, submitted_awaiting_coding: 4, in_coding: 1, coded: 7, refused: 1, not_codeable: 2, duplicate: 9 };
    expect(chipCount(counts, ["reported", "interview_pending", "interview_in_progress"])).toBe(6);
    // All leaves duplicate out.
    expect(chipCount(counts, allStatuses("deaths"))).toBe(21);
    expect(chipCount(undefined, ["coded"])).toBe(0);
  });

  test("Source goes to the server: Reported is register, Direct is direct and odk; only Deaths sends it", () => {
    const now = new Date("2026-11-01T12:00:00Z");
    const base = { projects: [], period: "all" as const, unit: null, site: null, status: null, overdue: false };
    expect(casesQuery({ ...base, tab: "deaths", source: "reported" }, ["P1"], now, null)).toMatchObject({ source: "register" });
    expect(casesQuery({ ...base, tab: "deaths", source: "direct" }, ["P1"], now, null)).toMatchObject({ source: "direct,odk" });
    expect(casesQuery({ ...base, tab: "deaths", source: null }, ["P1"], now, null).source).toBeNull();
    expect(casesQuery({ ...base, tab: "interviews", source: "direct" }, ["P1"], now, null).source).toBeNull();
  });

  test("days to code come from two server stamps", () => {
    expect(daysBetween("2026-10-01T08:00:00Z", "2026-10-11T07:00:00Z")).toBe(9);
    expect(daysBetween(null, "2026-10-11")).toBeNull();
    expect(daysBetween("garbage", "2026-10-11")).toBeNull();
  });
});

test("the stage-counts reply is checked: a missing number is an error, not a zero", async () => {
  const one = { reported: 1, interviewed: 1, coded: 0, overdue_interview: 0, overdue_coding: 0 };
  const good = { projects: { P1: one }, total: one, thresholds: { interview_days: 60, coding_days: 15 } };
  const request = jest.fn().mockResolvedValue(good);
  await expect(getStageCounts(request, { project_id: "P1", reported_from: null })).resolves.toEqual(good);
  expect(request).toHaveBeenCalledWith("/api/v1/cases/stage-counts?project_id=P1");
  const bad = jest.fn().mockResolvedValue({ ...good, projects: { P1: { ...one, coded: undefined } } });
  await expect(getStageCounts(bad, {})).rejects.toThrow("malformed_response");
});

test("the Area drop-down: All, the path, then what opens below", () => {
  const summary = {
    mode: "organization" as const,
    breadcrumb: [{ org_unit_id: "d1", code: "D", name: "District" }],
    rows: [
      { kind: "unit" as const, key: "b1", code: null, name: "Block", has_children: true, counts: {} as never },
      { kind: "unit" as const, key: "leaf", code: null, name: "Leaf", has_children: false, counts: {} as never },
    ],
  };
  expect(areaOptions(summary, null).map(({ value, kind, depth }) => [value, kind, depth])).toEqual([["", "all", 0], ["d1", "unit", 0], ["b1", "unit", 1]]);
  // With the user's units (case tabs) every unit under the current one is listed, leaves included.
  const units = [
    { org_unit_id: "d1", unit_name: "District", path: "d", is_active: true },
    { org_unit_id: "b1", unit_name: "Block", path: "d.b", is_active: true },
    { org_unit_id: "leaf", unit_name: "Leaf", path: "d.b.l", is_active: true },
    { org_unit_id: "off", unit_name: "Closed", path: "d.x", is_active: false },
    { org_unit_id: "other", unit_name: "Elsewhere", path: "e", is_active: true },
  ];
  expect(areaOptions(summary, null, units).map(({ value, depth }) => [value, depth])).toEqual([["", 0], ["d1", 0], ["b1", 1], ["leaf", 2]]);
  expect(areaOptions({ ...summary, breadcrumb: [] }, null, units).map(({ value, depth }) => [value, depth])).toEqual([["", 0], ["d1", 0], ["b1", 1], ["leaf", 2], ["other", 0]]);
  // A district user's one root: no All.
  expect(areaOptions(summary, "d1")[0].value).toBe("d1");
});

describe("formatting", () => {
  test("days keep one decimal and null stays null", () => {
    expect(formatDays(3.46)).toBe("3.5");
    expect(formatDays(4)).toBe("4");
    expect(formatDays(0)).toBe("0");
    expect(formatDays(null)).toBeNull();
  });
  test("percent drops a trailing .0", () => {
    expect(formatPercent(12.5)).toBe("12.5");
    expect(formatPercent(40)).toBe("40");
  });
});

describe("area api client", () => {
  test("GET only, project/unit/period encoded, unit and empty values left out", async () => {
    const request = jest.fn().mockResolvedValue({ projects: [] });
    await getAreaProjects(request);
    await getAreaSummary(request, { project: "P 1", unit: "u/1", period: "90d" });
    await getAreaSummary(request, { project: "P1", unit: null });
    await getAreaStaff(request, { project: "P1", unit: "u1" });
    expect(request.mock.calls.map(([path]) => path)).toEqual([
      "/api/v1/area/projects",
      "/api/v1/area/summary?project=P%201&unit=u%2F1&period=90d",
      "/api/v1/area/summary?project=P1&period=all",
      "/api/v1/area/staff?project=P1&unit=u1",
    ]);
    expect(request.mock.calls.every(([, init]) => init === undefined)).toBe(true);
  });

  test("the case list sends only given params and refuses a malformed reply", async () => {
    const page = { cases: [{ death_id: "d1", unique_id: "U1", status: "coded", overdue: null }], counts: { coded: 1 }, next_cursor: null };
    const request = jest.fn(async () => page);
    await expect(listCases(request, { preset: "deaths", project_id: "P1,P2", status: null, cursor: undefined, limit: "50" })).resolves.toEqual(page);
    expect(request).toHaveBeenCalledWith("/api/v1/cases?preset=deaths&project_id=P1%2CP2&limit=50");
    await expect(listCases(jest.fn(async () => ({ cases: [{ unique_id: "U1" }], next_cursor: null })), {})).rejects.toThrow("malformed_response");
    // A submission with no register row: a null death_id comes with its va_sid, never alone.
    const unregistered = { cases: [{ death_id: null, va_sid: "uuid:s1", unique_id: "U2", status: "coded" }], next_cursor: null };
    await expect(listCases(jest.fn(async () => unregistered), {})).resolves.toEqual(unregistered);
    await expect(listCases(jest.fn(async () => ({ cases: [{ death_id: null, unique_id: "U2", status: "coded" }], next_cursor: null })), {}))
      .rejects.toThrow("malformed_response");
    await expect(listCases(jest.fn(async () => ({ cases: [] })), {})).rejects.toThrow("malformed_response");
  });

  test("the csv link is the same level as a plain URL", () => {
    expect(areaCsvUrl({ project: "P1", unit: "u1", period: "12m" })).toBe("/api/v1/area/summary?project=P1&unit=u1&period=12m&format=csv");
    expect(areaCsvUrl({ project: "S1", site: "a" })).toBe("/api/v1/area/summary?project=S1&site=a&period=all&format=csv");
  });
});

test("the Statistics menu item stays current on its route", () => {
  expect(activeTab("/statistics")).toBe("/statistics");
});

describe("a district-level user's first level", () => {
  const top = { mode: "organization", project_wide: false, unit: null };
  const unitRow = (has_children: boolean) => ({ kind: "unit" as const, key: "u1", has_children });
  const none = { unit: null, site: null };

  test("a lone root with units below it opens at once", () => {
    expect(soleOpenUnit({ ...top, rows: [unitRow(true)] }, none)).toBe("u1");
  });

  test("not for a project-wide user, several roots, a leaf root, a chosen unit or a sites project", () => {
    expect(soleOpenUnit({ ...top, project_wide: true, rows: [unitRow(true)] }, none)).toBeNull();
    expect(soleOpenUnit({ ...top, rows: [unitRow(true), { ...unitRow(true), key: "u2" }] }, none)).toBeNull();
    expect(soleOpenUnit({ ...top, rows: [unitRow(false)] }, none)).toBeNull();
    expect(soleOpenUnit({ ...top, rows: [unitRow(true)] }, { unit: "u0", site: null })).toBeNull();
    expect(soleOpenUnit({ ...top, unit: { org_unit_id: "u0" }, rows: [unitRow(true)] }, none)).toBeNull();
    expect(soleOpenUnit({ ...top, mode: "sites", rows: [unitRow(true)] }, none)).toBeNull();
  });
});

describe("progressive project loading", () => {
  const load = (extra: Partial<ProjectLoad> = {}): ProjectLoad => ({ summary: null, error: "", fetching: false, ...extra });
  const summary = (id: string) => ({ project_id: id }) as never;

  test("only the summaries that arrived are kept, in order; pending and failed are counted apart", () => {
    const byId = { A: load({ summary: summary("A") }), B: load({ fetching: true }), C: load({ error: "boom" }) };
    expect(loadedSummaries(["C", "B", "A", "D"], byId)).toEqual([summary("A")]);
    expect(loadCounts(["A", "B", "C", "D"], byId)).toEqual({ pending: 2, failedIds: ["C"] });
    expect(loadCounts([], {})).toEqual({ pending: 0, failedIds: [] });
  });

  test("runLimited never has more than the limit in flight and still runs every id in order", async () => {
    let flying = 0;
    let peak = 0;
    const started: string[] = [];
    await runLimited(["a", "b", "c", "d", "e", "f", "g"], 3, async (id) => {
      started.push(id);
      flying += 1;
      peak = Math.max(peak, flying);
      await new Promise((resolve) => setTimeout(resolve, 1));
      flying -= 1;
    });
    expect(peak).toBe(3);
    expect(started).toEqual(["a", "b", "c", "d", "e", "f", "g"]);
    await expect(runLimited([], 4, async () => { throw new Error("never"); })).resolves.toBeUndefined();
  });
});

test("a count of 1 reads in the singular; other counts, a median of 1.0 and Hindi keep their forms", () => {
  expect(t(countKey("statsOverdueInterviews", 1), { count: 1, days: 60 })).toBe("1 death not interviewed after 60 days");
  expect(t(countKey("statsOverdueCodings", 1), { count: 1, days: 15 })).toBe("1 interview not coded after 15 days");
  expect(t(countKey("statsOverdueInterviews", 2), { count: 2, days: 60 })).toBe("2 deaths not interviewed after 60 days");
  expect(t(countKey("statsOverdueInterviews", 0), { count: 0, days: 60 })).toBe("0 deaths not interviewed after 60 days");
  expect(t(countKey("statsMedianInterview", formatDays(1)), { days: formatDays(1)! })).toBe("Median 1 day from death to interview");
  expect(t(countKey("statsMedianCod", formatDays(1.4)), { days: formatDays(1.4)! })).toBe("Median 1.4 days from interview to final cause of death");
  expect(t(countKey("statsLoadingMore", 1), { count: 1 })).toBe("Loading 1 more project…");
  expect(t(countKey("statsSomeFailed", 3), { count: 3 })).toBe("3 projects could not be loaded.");
  setUiLocale("hi");
  try {
    expect(t(countKey("statsOverdueCodings", 1), { count: 1, days: 15 })).toBe("1 साक्षात्कार 15 दिन बाद भी कोड नहीं हुआ");
  } finally {
    setUiLocale("en");
  }
});
