import type { CodAggregates, CodRow } from "../src/data/api";
import { codExportUrl } from "../src/data/api";
import { ageKey, ageSexTotals, buildTree, causesApiParams, causesPatch, groupsFor, parseCausesQuery, scopeSections, topCausesFor } from "../src/data/causes";

const row = (over: Partial<CodRow>): CodRow => ({
  age_scope: "adult_over5y", age_scope_label: "Adult / Over 5 Years", age_scope_sort_order: 2, bucket_category: "Infectious", bucket_subcategory: null,
  bucket_field: "Malaria", coded_count: 3, male_count: 2, female_count: 1, unknown_count: 0, ...over,
});

describe("Causes URL mapping", () => {
  test("the URL names map to the API names; empty values are left out", () => {
    const query = parseCausesQuery({ scheme_code: "WHO_2022_VA", project: "ICMR01", site: "NC02", form_id: "ICMR01NC0201", gender: "female", date_from: "2026-01-02", date_to: "2026-02-03", age: "neonate" });
    expect(causesApiParams(query)).toEqual({ scheme_code: "WHO_2022_VA", project_id: "ICMR01", site_id: "NC02", form_id: "ICMR01NC0201", gender: "female", date_from: "2026-01-02", date_to: "2026-02-03" });
    expect(causesApiParams(parseCausesQuery({}))).toEqual({});
    expect(codExportUrl(causesApiParams(query))).toBe(
      "/api/v1/cod-buckets/export.csv?scheme_code=WHO_2022_VA&project_id=ICMR01&site_id=NC02&form_id=ICMR01NC0201&gender=female&date_from=2026-01-02&date_to=2026-02-03",
    );
  });

  test("the age choice is a view of the payload, not an API filter; its keys can hold spaces and symbols", () => {
    expect(causesApiParams(parseCausesQuery({ age: "neonate" }))).toEqual({});
    expect(parseCausesQuery({ age: "0-<28 days" }).age).toBe("0-<28 days");
  });

  test("a bad date goes through for the server to refuse; junk and lists do not", () => {
    expect(parseCausesQuery({ date_from: "nope" }).date_from).toBe("nope");
    expect(parseCausesQuery({ date_from: "a b;<script>" }).date_from).toBe("");
    expect(parseCausesQuery({ project: "P1,P2", site: "../x", scheme_code: "x y" })).toMatchObject({ project: "", site: "", scheme_code: "" });
    expect(parseCausesQuery({ form_id: ["F1", "F2"] }).form_id).toBe("F1");
  });

  test("causesPatch names every key and unsets the empty ones", () => {
    expect(causesPatch(parseCausesQuery({ project: "P1" }))).toEqual({
      scheme_code: undefined, project: "P1", site: undefined, form_id: undefined, gender: undefined, date_from: undefined, date_to: undefined, age: undefined,
    });
  });
});

describe("Causes payload shaping", () => {
  const summary = {
    top_causes: [{ rank: 1, display_label: "All", coded_count: 5, percent: 100 }],
    top_causes_by_age: { neonate: [{ rank: 1, display_label: "Neo", coded_count: 2, percent: 100 }] },
    first_level_counts: [{ label: "G", coded_count: 5, percent: 100 }],
    first_level_counts_by_age: {},
    age_filters: [{ key: "all", label: "All ages" }, { key: "neonate", label: "Neonate" }],
  } as unknown as CodAggregates["summary"];

  test("the age filter picks the per-age list, and falls back to all for an unknown key", () => {
    expect(topCausesFor(summary, "neonate")[0].display_label).toBe("Neo");
    expect(topCausesFor(summary, "all")[0].display_label).toBe("All");
    expect(groupsFor(summary, "neonate")[0].label).toBe("G");
    expect(ageKey("neonate", summary.age_filters)).toBe("neonate");
    expect(ageKey("zzz", summary.age_filters)).toBe("all");
  });

  test("rows become category > subcategory > disease nodes with counts summed upward", () => {
    const tree = buildTree([
      row({}),
      row({ bucket_subcategory: "Vector", bucket_field: "Dengue", coded_count: 2, male_count: 1, female_count: 1 }),
      row({ bucket_category: "Injury", bucket_field: "Road", coded_count: 1, male_count: 1, female_count: 0 }),
      row({ bucket_category: null, bucket_field: null, coded_count: 1, male_count: 0, female_count: 0, unknown_count: 1 }),
    ]);
    expect(tree.map((node) => [node.label, node.total])).toEqual([["Infectious", 5], ["Injury", 1], ["Unknown", 1]]);
    const infectious = tree[0];
    expect(infectious).toMatchObject({ male: 3, female: 2, unknown: 0, level: 0 });
    expect(infectious.children.map((node) => [node.label, node.level, node.total])).toEqual([["Malaria", 2 as number, 3], ["Vector", 1, 2]]);
    expect(infectious.children[1].children[0]).toMatchObject({ label: "Dengue", level: 2, total: 2 });
  });

  test("sections: All ages first, then by sort order; unmatched-only scopes still appear with their dropped ICDs", () => {
    const sections = scopeSections({
      data: [row({}), row({ age_scope: null, age_scope_label: null, age_scope_sort_order: null }), row({ age_scope: "neonate", age_scope_label: "Neonate", age_scope_sort_order: 1 })],
      summary: {
        unmatched_by_age_scope: [{ age_scope: "child_1_59m", age_scope_label: "Child", age_scope_sort_order: 3, unmatched_count: 4 }],
        unmatched_icd_breakdown: [{ age_scope: "child_1_59m", category: "not_included_in_scheme", icd_code: "A00", unmatched_count: 4 }],
      },
    } as unknown as CodAggregates);
    expect(sections.map((section) => section.label)).toEqual(["All ages", "Neonate", "Adult / Over 5 Years", "Child"]);
    const child = sections[3];
    expect(child).toMatchObject({ unmatched: 4, total: 0, tree: [] });
    expect(child.dropped).toHaveLength(1);
    expect(sections[2].total).toBe(3);
  });

  test("age and sex totals add the columns", () => {
    expect(ageSexTotals([
      { age_band: "0-4", male_count: 1, female_count: 2, unknown_count: 0, total_count: 3, total_percent: 60 },
      { age_band: "5-9", male_count: 1, female_count: 0, unknown_count: 1, total_count: 2, total_percent: 40 },
    ])).toEqual({ male: 2, female: 2, unknown: 1, total: 5 });
  });
});
