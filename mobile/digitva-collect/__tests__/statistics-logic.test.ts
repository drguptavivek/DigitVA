import { activeTab } from "../src/web/navTabs";
import { areaCsvUrl, getAreaProjects, getAreaStaff, getAreaSummary } from "../src/area/api";
import { canDrill, formatDays, formatPercent, hasDeathRegister, parseSelection, pipelineScale, selectionParams, stageWidths } from "../src/web/stats/pipeline";

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

describe("selection from the URL", () => {
  const projects = [{ project_id: "P1", mode: "organization" as const }, { project_id: "S1", mode: "sites" as const }];

  test("valid names are kept; unknown project and period fall back; arrays use the first value", () => {
    expect(parseSelection({ project: "P1", unit: "u1", period: "90d" }, projects)).toEqual({ project: "P1", unit: "u1", site: null, period: "90d" });
    expect(parseSelection({ project: "nope", period: "weekly" }, projects)).toEqual({ project: "P1", unit: null, site: null, period: "all" });
    expect(parseSelection({ project: ["S1", "P1"], site: ["a"] }, projects)).toEqual({ project: "S1", unit: null, site: "a", period: "all" });
    expect(parseSelection({}, [])).toBeNull();
  });

  test("unit applies to organization projects only, site to sites projects only; long values are dropped", () => {
    expect(parseSelection({ project: "P1", site: "x" }, projects)?.site).toBeNull();
    expect(parseSelection({ project: "S1", unit: "x" }, projects)?.unit).toBeNull();
    expect(parseSelection({ project: "P1", unit: "u".repeat(65) }, projects)?.unit).toBeNull();
  });

  test("params leave out empty values and the default period", () => {
    expect(selectionParams({ project: "P1", unit: null, site: null, period: "all" })).toEqual({ project: "P1" });
    expect(selectionParams({ project: "S1", unit: null, site: "a", period: "12m" })).toEqual({ project: "S1", site: "a", period: "12m" });
  });
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

  test("the csv link is the same level as a plain URL", () => {
    expect(areaCsvUrl({ project: "P1", unit: "u1", period: "12m" })).toBe("/api/v1/area/summary?project=P1&unit=u1&period=12m&format=csv");
    expect(areaCsvUrl({ project: "S1", site: "a" })).toBe("/api/v1/area/summary?project=S1&site=a&period=all&format=csv");
  });
});

test("the Statistics menu item stays current on its route", () => {
  expect(activeTab("/statistics")).toBe("/statistics");
});
