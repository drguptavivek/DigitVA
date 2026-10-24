import { dmExportUrl, dmQuery } from "../src/data/api";
import {
  activeFilters, applyCard, CARDS, cardActive, clearFilters, columnsFor, countApiParams, dataRouteForLink, exportApiParams,
  FILTER_KEYS, isStaleResult, listApiParams, matchGender, paramsPatch, parseDataQuery, queryParams, sortBy, visibleColumns, withCoder, withFilters,
} from "../src/data/query";
import { dataAccess } from "../src/web/roleHome";

const card = (key: string) => CARDS.find((one) => one.key === key)!;
const boot = (roles: string[], is_admin = false) => ({ access: { roles, is_admin }, capabilities: {} }) as unknown as Parameters<typeof dataAccess>[0];

describe("URL <-> filters", () => {
  test("an empty URL is the Flask default: in sync, newest first, page 1 of 25", () => {
    const query = parseDataQuery({});
    expect(query.filters.odk_sync).toBe("in_sync");
    expect(query).toMatchObject({ page: 1, size: 25, sortField: "va_submission_date", sortDir: "desc", selectedSid: "" });
    expect(queryParams(query)).toEqual({});
  });

  test("every filter, sort, page, size and selected row round-trips with the Flask names", () => {
    const raw = {
      search: "ab", project: "P1,P2", site: "S1", date_from: "2026-01-02", date_to: "2026-02-03", odk_status: "hasIssues", smartva: "failed",
      age_group: "15_49y", gender: "female", odk_sync: "all", workflow: "coded", visit_note: "1", org_unit: "11111111-2222-3333-4444-555555555555",
      page: "3", size: "50", sort_field: "coded_by", sort_dir: "asc", selected_sid: "uuid-1",
    };
    expect(queryParams(parseDataQuery(raw))).toEqual(raw);
  });

  test("malformed values fall back; an empty odk_sync is the default, not 'all'", () => {
    const query = parseDataQuery({
      odk_status: "x", smartva: "y", age_group: "z", workflow: "nope", date_from: "yesterday", visit_note: "2", odk_sync: "", page: "-4", size: "7", sort_field: "password", sort_dir: "sideways",
      project: "a;b", org_unit: "../x",
    });
    expect(query.filters).toMatchObject({ odk_status: "", smartva: "", age_group: "", workflow: "", date_from: "", visit_note: "", odk_sync: "in_sync", project: "", org_unit: "" });
    expect(query).toMatchObject({ page: 1, size: 25, sortField: "va_submission_date", sortDir: "desc" });
  });

  test("array params use the first value; page and text are capped", () => {
    expect(parseDataQuery({ search: ["one", "two"], page: "99999999" }).filters.search).toBe("one");
    expect(parseDataQuery({ page: "99999999" }).page).toBe(100000);
    expect(parseDataQuery({ search: "x".repeat(500) }).filters.search).toHaveLength(200);
  });

  test("the chips list exactly the filters off their default", () => {
    expect(activeFilters(parseDataQuery({}).filters)).toEqual([]);
    expect(activeFilters(parseDataQuery({ workflow: "coded", odk_sync: "missing_in_odk" }).filters).map((chip) => chip.key)).toEqual(["odk_sync", "workflow"]);
    expect(parseDataQuery({ workflow: "coded", odk_sync: "all", page: "4" }) && clearFilters(parseDataQuery({ workflow: "coded", odk_sync: "all", page: "4" }))).toMatchObject({ page: 1 });
    expect(queryParams(clearFilters(parseDataQuery({ workflow: "coded", odk_sync: "all", size: "10" })))).toEqual({ size: "10" });
  });

  test("a filter change returns to page 1 and drops the selected row", () => {
    const next = withFilters(parseDataQuery({ page: "5", selected_sid: "a" }), { smartva: "missing" });
    expect(next).toMatchObject({ page: 1, selectedSid: "" });
    expect(next.filters.smartva).toBe("missing");
  });
});

describe("sort mapping", () => {
  test("the API gets sort[0][field] and sort[0][dir]", () => {
    const params = listApiParams(parseDataQuery({ sort_field: "site_id", sort_dir: "asc", page: "2", size: "10", workflow: "coded" }));
    expect(params).toMatchObject({ "sort[0][field]": "site_id", "sort[0][dir]": "asc", page: "2", size: "10", workflow: "coded", odk_sync: "in_sync" });
    expect(dmQuery(params)).toContain("sort%5B0%5D%5Bfield%5D=site_id");
  });

  test("a header press flips the same column and starts a new one ascending, dates newest first", () => {
    const base = parseDataQuery({});
    expect(sortBy(base, "va_submission_date")).toMatchObject({ sortField: "va_submission_date", sortDir: "asc" });
    expect(sortBy(base, "site_id")).toMatchObject({ sortField: "site_id", sortDir: "asc", page: 1 });
    expect(sortBy(base, "coded_on")).toMatchObject({ sortDir: "desc" });
  });

  test("only the allowed sort fields survive the URL", () => {
    expect(parseDataQuery({ sort_field: "va_data_collector" }).sortField).toBe("va_submission_date");
  });
});

describe("cards", () => {
  test("the eleven cards click to the filters the spec lists; Total has none", () => {
    expect(CARDS).toHaveLength(11);
    expect(Object.fromEntries(CARDS.filter((one) => one.filter).map((one) => [one.key, one.filter]))).toEqual({
      pending: { workflow: "pending_coding" }, smartvaPending: { workflow: "smartva_pending" }, coded: { workflow: "coded" },
      upstream: { workflow: "finalized_upstream_changed" }, attention: { odk_status: "hasIssues" },
      notCodeable: { workflow: "not_codeable_by_data_manager" }, notAnalysable: { workflow: "consent_refused" },
      missingOdk: { odk_sync: "missing_in_odk" }, smartvaMissing: { smartva: "missing" }, smartvaFailed: { smartva: "failed" },
    });
    expect(card("total").filter).toBeUndefined();
  });

  test("a click adds the filter on page 1; a second click lifts it (odk_sync back to in sync)", () => {
    const start = parseDataQuery({ page: "3", search: "x" });
    const coded = applyCard(start, card("coded"));
    expect(coded).toMatchObject({ page: 1 });
    expect(coded.filters).toMatchObject({ workflow: "coded", search: "x" });
    expect(cardActive(card("coded"), coded.filters)).toBe(true);
    expect(applyCard(coded, card("coded")).filters.workflow).toBe("");
    const missing = applyCard(start, card("missingOdk"));
    expect(missing.filters.odk_sync).toBe("missing_in_odk");
    expect(applyCard(missing, card("missingOdk")).filters.odk_sync).toBe("in_sync");
    expect(applyCard(start, card("total"))).toBe(start);
  });

  test("the counts and charts ignore search, visit note and unit; the exports keep search only", () => {
    const filters = parseDataQuery({ search: "a", visit_note: "1", org_unit: "u1", workflow: "coded" }).filters;
    expect(countApiParams(filters)).toEqual({ workflow: "coded", odk_sync: "in_sync" });
    expect(exportApiParams(filters)).toEqual({ search: "a", workflow: "coded", odk_sync: "in_sync" });
    expect(dmExportUrl("data", exportApiParams(filters))).toBe("/api/v1/data-management/submissions/export.csv?search=a&odk_sync=in_sync&workflow=coded");
  });
});

describe("redaction", () => {
  test("a plain collaborator has no collector or coded-by column and cannot sort by coder", () => {
    expect(columnsFor(true).map((column) => column.key)).not.toContain("va_data_collector");
    expect(columnsFor(true).map((column) => column.key)).not.toContain("coded_by");
    expect(columnsFor(false).map((column) => column.key)).toEqual(expect.arrayContaining(["va_data_collector", "coded_by"]));
    expect(visibleColumns(true, { va_data_collector: true, coded_by: true }).map((column) => column.key)).not.toContain("coded_by");
    expect(parseDataQuery({ sort_field: "coded_by", sort_dir: "asc" }, true)).toMatchObject({ sortField: "va_submission_date", sortDir: "desc" });
    expect(parseDataQuery({ sort_field: "coded_by", sort_dir: "asc" }, false)).toMatchObject({ sortField: "coded_by", sortDir: "asc" });
  });

  test("the default columns are the Flask page's", () => {
    expect(visibleColumns(false).map((column) => column.key)).toEqual([
      "site_id", "va_submission_date", "va_uniqueid_masked", "has_smartva", "va_odk_reviewstate", "workflow_state", "coded_on", "coded_by", "visit_note",
    ]);
    expect(visibleColumns(false, { attachment_count: true, workflow_state: false }).map((column) => column.key)).toContain("attachment_count");
  });

  test("who is a manager, who a viewer, who is redacted", () => {
    expect(dataAccess(boot(["data_manager"]))).toEqual({ allowed: true, manage: true, redacted: false });
    expect(dataAccess(boot([], true))).toEqual({ allowed: true, manage: true, redacted: false });
    expect(dataAccess(boot(["admin"]))).toMatchObject({ allowed: true, manage: true });
    expect(dataAccess(boot(["collaborator"]))).toEqual({ allowed: true, manage: false, redacted: true });
    expect(dataAccess(boot(["collaborator_pii"]))).toEqual({ allowed: true, manage: false, redacted: false });
    expect(dataAccess(boot(["collaborator", "coder"])).redacted).toBe(false);
    for (const role of ["coder", "site_pi", "project_pi", "interviewer", "interview_supervisor"]) expect(dataAccess(boot([role])).allowed).toBe(false);
    expect(dataAccess({} as never).allowed).toBe(false);
  });
});

describe("links from Statistics", () => {
  test("a Flask data management link becomes a Data route with the same filters", () => {
    expect(dataRouteForLink("/data-management/?project=P1&site=S1&date_from=2026-01-01&visit_note=1&search=&odk_sync=")).toEqual({
      project: "P1", site: "S1", date_from: "2026-01-01", visit_note: "1",
    });
    expect(dataRouteForLink("/data-management")).toEqual({});
  });

  test("any other path or origin stays a server page", () => {
    expect(dataRouteForLink("/data-management/dashboard")).toBeNull();
    expect(dataRouteForLink("/intake/")).toBeNull();
    expect(dataRouteForLink("https://evil.example/data-management/?project=P")).toBeNull();
  });

  test("a gender picked in a panel matches the server's spelling", () => {
    expect(matchGender(["male", "female"], "Male")).toBe("male");
    expect(matchGender(["male"], "other")).toBe("");
    expect(matchGender([], null)).toBe("");
  });
});

describe("Part A rules", () => {
  test("paramsPatch names every key and leaves defaults unset, so setParams clears them", () => {
    const patch = paramsPatch(parseDataQuery({}));
    expect(Object.keys(patch)).toEqual(expect.arrayContaining([...FILTER_KEYS, "page", "size", "sort_field", "sort_dir", "selected_sid"]));
    expect(Object.values(patch).every((value) => value === undefined)).toBe(true);
    expect(paramsPatch(parseDataQuery({ workflow: "coded", page: "2" }))).toMatchObject({ workflow: "coded", page: "2", size: undefined });
    expect(paramsPatch(parseDataQuery({ workflow: "coded" })).tab).toBeUndefined();
  });

  test("dmQuery and dmExportUrl encode the sort brackets, comma lists and search text, and skip empty values", () => {
    const params = listApiParams(parseDataQuery({ project: "P1,P2", search: "a b&c=d", sort_field: "coded_on", sort_dir: "asc" }));
    const parsed = new URLSearchParams(dmQuery(params));
    expect(parsed.get("sort[0][field]")).toBe("coded_on");
    expect(parsed.get("sort[0][dir]")).toBe("asc");
    expect(parsed.get("project")).toBe("P1,P2");
    expect(parsed.get("search")).toBe("a b&c=d");
    expect(dmQuery(params)).toContain("sort%5B0%5D%5Bfield%5D=coded_on");
    expect(dmQuery(params)).not.toContain("a b&c");
    expect(dmQuery({ a: "", b: "" })).toBe("");
    const url = dmExportUrl("coded_cod_snapshot", exportApiParams(parseDataQuery({ search: "x y", site: "S1,S2" }).filters));
    expect(url).toBe("/api/v1/data-management/submissions/export-coded-cod-snapshot.csv?search=x+y&site=S1%2CS2&odk_sync=in_sync");
  });

  test("rows of an earlier query are stale only when the current query's fetch failed", () => {
    expect(isStaleResult("a", "b", "boom")).toBe(true);
    expect(isStaleResult("a", "a", "boom")).toBe(false);
    expect(isStaleResult("a", "b", "")).toBe(false);
    expect(isStaleResult(undefined, "b", "boom")).toBe(false);
  });

  test("a clicked coder reaches the list and export requests but never the URL", () => {
    const query = parseDataQuery({ search: "typed", workflow: "coded" });
    const narrowed = withCoder(query, "Dr Asha");
    expect(listApiParams(narrowed).search).toBe("Dr Asha");
    expect(exportApiParams(narrowed.filters).search).toBe("Dr Asha");
    // The URL view is untouched: the typed search stays, and the coder name appears in no URL param.
    expect(query.filters.search).toBe("typed");
    expect(Object.values(queryParams(query))).not.toContain("Dr Asha");
    expect(Object.values(paramsPatch(query))).not.toContain("Dr Asha");
    expect(withCoder(query, "")).toBe(query);
  });
});
