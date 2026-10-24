/**
 * Pure rules of the Data screen: the URL <-> filter mapping, the sort mapping, the card -> filter mapping, the
 * columns a viewer may see, and the Flask-link -> Data-route mapping. No React, so each is unit-tested directly.
 * The URL is untrusted: every value is checked here, and the server scopes every number anyway.
 */
import type { DmKpi, DmParams } from "./api";

/** The filter names, identical in the URL, the API and the Flask page. */
export const FILTER_KEYS = [
  "search", "project", "site", "date_from", "date_to", "odk_status", "smartva", "age_group", "gender",
  "odk_sync", "workflow", "visit_note", "org_unit",
] as const;
export type FilterKey = (typeof FILTER_KEYS)[number];
export type Filters = Record<FilterKey, string>;

/** Filters the counts, charts and exports honour. Search, visit note and unit are list-only (the exports also take search). */
const COUNT_KEYS: readonly FilterKey[] = ["project", "site", "date_from", "date_to", "odk_status", "smartva", "age_group", "gender", "odk_sync", "workflow"];
const EXPORT_KEYS: readonly FilterKey[] = ["search", ...COUNT_KEYS];

export const ODK_STATUSES = ["hasIssues", "approved", "no_review_state"] as const;
export const SMARTVA_VALUES = ["available", "missing", "failed"] as const;
export const AGE_GROUPS = ["neonate", "child", "15_49y", "50_64y", "65_plus", "unknown"] as const;
export const ODK_SYNC_VALUES = ["in_sync", "missing_in_odk", "all"] as const;
export const WORKFLOW_GROUPS = ["pending_coding", "coded"] as const;
export const WORKFLOW_STATES = [
  "attachment_sync_pending", "ready_for_coding", "smartva_pending", "screening_pending",
  "coding_in_progress", "coder_step1_saved", "not_codeable_by_coder",
  "coder_finalized", "reviewer_eligible", "reviewer_coding_in_progress", "reviewer_finalized",
  "finalized_upstream_changed", "sent_back_for_revision", "not_codeable_by_data_manager", "consent_refused",
] as const;
export const WORKFLOW_VALUES: readonly string[] = [...WORKFLOW_GROUPS, ...WORKFLOW_STATES];

export const SORT_FIELDS = [
  "va_uniqueid_masked", "project_id", "site_id", "workflow_state", "va_dmreview_createdat", "va_submission_date", "coded_on", "coded_by",
] as const;
export type SortField = (typeof SORT_FIELDS)[number];
export type SortDir = "asc" | "desc";

export const PAGE_SIZES = [10, 25, 50, 100] as const;
export const DEFAULT_SIZE = 25;
export const DEFAULT_SORT: { field: SortField; dir: SortDir } = { field: "va_submission_date", dir: "desc" };
export const DEFAULT_ODK_SYNC = "in_sync";

export interface DataQuery {
  filters: Filters;
  page: number;
  size: number;
  sortField: SortField;
  sortDir: SortDir;
  selectedSid: string;
}

type RawParam = string | string[] | undefined;
type RawParams = Partial<Record<string, RawParam>>;

const one = (value: RawParam): string => ((Array.isArray(value) ? value[0] : value) ?? "").trim();
const MAX_TEXT = 200;
const MAX_PAGE = 100000;
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const TOKEN = /^[\w .,:\-/]+$/;

const oneOf = (value: string, allowed: readonly string[]) => (allowed.includes(value) ? value : "");

/** A comma list of ids (project, site): each part a short token, at most 20 parts. */
function idList(value: string): string {
  if (!value || value.length > MAX_TEXT) return "";
  const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
  return parts.length <= 20 && parts.every((part) => TOKEN.test(part)) ? parts.join(",") : "";
}

export const emptyFilters = (): Filters => ({
  search: "", project: "", site: "", date_from: "", date_to: "", odk_status: "", smartva: "", age_group: "", gender: "",
  odk_sync: DEFAULT_ODK_SYNC, workflow: "", visit_note: "", org_unit: "",
});

/**
 * The view named by the URL. Unknown or malformed values fall back to the default (no filter; in sync; newest first;
 * page 1 of 25). A redacted viewer asking for the coded-by sort gets the default sort: the column is hidden, and the
 * server refuses the sort for them anyway (digitva-10fd).
 */
export function parseDataQuery(raw: RawParams, redacted = false): DataQuery {
  const filters: Filters = {
    search: one(raw.search).slice(0, MAX_TEXT),
    project: idList(one(raw.project)),
    site: idList(one(raw.site)),
    date_from: DATE.test(one(raw.date_from)) ? one(raw.date_from) : "",
    date_to: DATE.test(one(raw.date_to)) ? one(raw.date_to) : "",
    odk_status: oneOf(one(raw.odk_status), ODK_STATUSES),
    smartva: oneOf(one(raw.smartva), SMARTVA_VALUES),
    age_group: oneOf(one(raw.age_group), AGE_GROUPS),
    gender: one(raw.gender).length <= 40 && TOKEN.test(one(raw.gender)) ? one(raw.gender) : "",
    odk_sync: oneOf(one(raw.odk_sync), ODK_SYNC_VALUES) || DEFAULT_ODK_SYNC,
    workflow: oneOf(one(raw.workflow), WORKFLOW_VALUES),
    visit_note: one(raw.visit_note) === "1" ? "1" : "",
    org_unit: /^[\w-]{1,64}$/.test(one(raw.org_unit)) ? one(raw.org_unit) : "",
  };
  const page = Number.parseInt(one(raw.page), 10);
  const size = Number.parseInt(one(raw.size), 10);
  const field = oneOf(one(raw.sort_field), SORT_FIELDS) as SortField | "";
  const usable = field && !(redacted && field === "coded_by");
  return {
    filters,
    page: Number.isInteger(page) && page >= 1 ? Math.min(page, MAX_PAGE) : 1,
    size: (PAGE_SIZES as readonly number[]).includes(size) ? size : DEFAULT_SIZE,
    sortField: usable ? field : DEFAULT_SORT.field,
    sortDir: usable ? (one(raw.sort_dir).toLowerCase() === "asc" ? "asc" : "desc") : DEFAULT_SORT.dir,
    selectedSid: one(raw.selected_sid).slice(0, 128),
  };
}

/** URL params of a view; empty values and defaults are left out so shared links stay short. */
export function queryParams(query: DataQuery): Record<string, string> {
  const params: Record<string, string> = {};
  for (const key of FILTER_KEYS) {
    const value = query.filters[key];
    if (value && !(key === "odk_sync" && value === DEFAULT_ODK_SYNC)) params[key] = value;
  }
  if (query.page > 1) params.page = String(query.page);
  if (query.size !== DEFAULT_SIZE) params.size = String(query.size);
  if (query.sortField !== DEFAULT_SORT.field || query.sortDir !== DEFAULT_SORT.dir) {
    params.sort_field = query.sortField;
    params.sort_dir = query.sortDir;
  }
  if (query.selectedSid) params.selected_sid = query.selectedSid;
  return params;
}

/**
 * Every URL key of the view with its value, `undefined` where it is at its default: what router.setParams needs to
 * rewrite the query in place (it merges, so an omitted key would linger). The screen changes the query in place
 * rather than pushing: a stacked route keeps every earlier view mounted, and each holds a page of table rows.
 */
export function paramsPatch(query: DataQuery): Record<string, string | undefined> {
  const set = queryParams(query);
  return Object.fromEntries([...FILTER_KEYS, "page", "size", "sort_field", "sort_dir", "selected_sid"].map((key) => [key, set[key]]));
}

const pick = (filters: Filters, keys: readonly FilterKey[]): DmParams => {
  const out: DmParams = {};
  for (const key of keys) if (filters[key]) out[key] = filters[key];
  return out;
};

/** GET /submissions: every filter, the page, and the sort as the API names it (`sort[0][field]`, `sort[0][dir]`). */
export function listApiParams(query: DataQuery): DmParams {
  return {
    ...pick(query.filters, FILTER_KEYS),
    page: String(query.page),
    size: String(query.size),
    "sort[0][field]": query.sortField,
    "sort[0][dir]": query.sortDir,
  };
}

/** The counts, charts and exports ignore search, visit note and unit (the exports still take search). */
export const countApiParams = (filters: Filters): DmParams => pick(filters, COUNT_KEYS);
export const exportApiParams = (filters: Filters): DmParams => pick(filters, EXPORT_KEYS);

/**
 * The view as the API should see it while a coder's name (clicked in the coder panel) narrows the list: the name
 * replaces the typed search in the requests only. It lives in component state, so it never reaches the URL or history.
 */
export const withCoder = (query: DataQuery, coder: string): DataQuery =>
  coder ? { ...query, filters: { ...query.filters, search: coder } } : query;

/** True when the last fetch for the current query failed and the rows on screen are an earlier query's. */
export const isStaleResult = (loadedKey: string | undefined, currentKey: string, error: string): boolean =>
  Boolean(error) && loadedKey !== undefined && loadedKey !== currentKey;

/** The view with *patch* applied to its filters; any filter change goes back to page 1 and drops the selected row. */
export function withFilters(query: DataQuery, patch: Partial<Filters>): DataQuery {
  return { ...query, filters: { ...query.filters, ...patch }, page: 1, selectedSid: "" };
}

/** Every filter back to its default; sort and page size stay. */
export const clearFilters = (query: DataQuery): DataQuery => ({ ...query, filters: emptyFilters(), page: 1, selectedSid: "" });

/** Filters that are not at their default, in display order: what the chips show. */
export function activeFilters(filters: Filters): { key: FilterKey; value: string }[] {
  return FILTER_KEYS
    .filter((key) => filters[key] && !(key === "odk_sync" && filters[key] === DEFAULT_ODK_SYNC))
    .map((key) => ({ key, value: filters[key] }));
}

/** Sorting by a header: the same field flips the direction; a new field starts ascending (newest first for dates). */
export function sortBy(query: DataQuery, field: SortField): DataQuery {
  const sameField = query.sortField === field;
  const dateField = field === "va_submission_date" || field === "coded_on" || field === "va_dmreview_createdat";
  const sortDir: SortDir = sameField ? (query.sortDir === "asc" ? "desc" : "asc") : dateField ? "desc" : "asc";
  return { ...query, sortField: field, sortDir, page: 1, selectedSid: "" };
}

export type CardKey =
  | "total" | "pending" | "smartvaPending" | "coded" | "upstream" | "attention" | "notCodeable"
  | "notAnalysable" | "missingOdk" | "smartvaMissing" | "smartvaFailed";

export interface CardDef {
  key: CardKey;
  count: (kpi: DmKpi) => number;
  /** The one filter a click sets; the Total card has none and is not a button. */
  filter?: Partial<Filters>;
}

export const CARDS: CardDef[] = [
  { key: "total", count: (kpi) => kpi.total_submissions },
  { key: "pending", count: (kpi) => kpi.pending_submissions, filter: { workflow: "pending_coding" } },
  { key: "smartvaPending", count: (kpi) => kpi.smartva_pending_submissions, filter: { workflow: "smartva_pending" } },
  { key: "coded", count: (kpi) => kpi.coded_submissions, filter: { workflow: "coded" } },
  { key: "upstream", count: (kpi) => kpi.revoked_submissions, filter: { workflow: "finalized_upstream_changed" } },
  { key: "attention", count: (kpi) => kpi.odk_has_issues_submissions, filter: { odk_status: "hasIssues" } },
  { key: "notCodeable", count: (kpi) => kpi.flagged_submissions, filter: { workflow: "not_codeable_by_data_manager" } },
  { key: "notAnalysable", count: (kpi) => kpi.not_analysable_submissions, filter: { workflow: "consent_refused" } },
  { key: "missingOdk", count: (kpi) => kpi.missing_in_odk_submissions, filter: { odk_sync: "missing_in_odk" } },
  { key: "smartvaMissing", count: (kpi) => kpi.smartva_missing_submissions, filter: { smartva: "missing" } },
  { key: "smartvaFailed", count: (kpi) => kpi.smartva_failed_submissions, filter: { smartva: "failed" } },
];

/** True when the view already carries the card's filter. */
export const cardActive = (card: CardDef, filters: Filters): boolean =>
  Boolean(card.filter) && Object.entries(card.filter!).every(([key, value]) => filters[key as FilterKey] === value);

/** A card click: its filter on top of the current ones (a second click on the active card lifts it). */
export function applyCard(query: DataQuery, card: CardDef): DataQuery {
  if (!card.filter) return query;
  if (cardActive(card, query.filters)) {
    const lifted: Partial<Filters> = {};
    for (const key of Object.keys(card.filter) as FilterKey[]) lifted[key] = key === "odk_sync" ? DEFAULT_ODK_SYNC : "";
    return withFilters(query, lifted);
  }
  return withFilters(query, card.filter);
}

export type ColumnKey =
  | "site_id" | "project_id" | "va_submission_date" | "va_uniqueid_masked" | "va_data_collector" | "attachment_count"
  | "has_smartva" | "va_odk_reviewstate" | "analytics_age_band" | "va_deceased_gender" | "odk_sync_status"
  | "workflow_state" | "coded_on" | "coded_by" | "va_dmreview_createdat" | "va_consent" | "visit_note";

export interface ColumnDef {
  key: ColumnKey;
  sort?: SortField;
  /** Shown unless the viewer turns it off; the others start hidden, as on the Flask page. */
  defaultVisible: boolean;
  /** Staff identity: absent for a redacted viewer. */
  staff?: boolean;
}

export const COLUMNS: ColumnDef[] = [
  { key: "project_id", sort: "project_id", defaultVisible: false },
  { key: "site_id", sort: "site_id", defaultVisible: true },
  { key: "va_submission_date", sort: "va_submission_date", defaultVisible: true },
  { key: "va_uniqueid_masked", sort: "va_uniqueid_masked", defaultVisible: true },
  { key: "va_data_collector", defaultVisible: false, staff: true },
  { key: "attachment_count", defaultVisible: false },
  { key: "has_smartva", defaultVisible: true },
  { key: "analytics_age_band", defaultVisible: false },
  { key: "va_deceased_gender", defaultVisible: false },
  { key: "va_odk_reviewstate", defaultVisible: true },
  { key: "odk_sync_status", defaultVisible: false },
  { key: "workflow_state", sort: "workflow_state", defaultVisible: true },
  { key: "coded_on", sort: "coded_on", defaultVisible: true },
  { key: "coded_by", sort: "coded_by", defaultVisible: true, staff: true },
  { key: "va_dmreview_createdat", sort: "va_dmreview_createdat", defaultVisible: false },
  { key: "va_consent", defaultVisible: false },
  { key: "visit_note", defaultVisible: true },
];

/** Columns this viewer may have: a redacted viewer has no data collector or coded-by column at all. */
export const columnsFor = (redacted: boolean): ColumnDef[] => COLUMNS.filter((column) => !(redacted && column.staff));

/** The columns shown: *changed* holds the viewer's on/off choices over the defaults; columns the viewer may not have are never shown. */
export function visibleColumns(redacted: boolean, changed: Partial<Record<ColumnKey, boolean>> = {}): ColumnDef[] {
  return columnsFor(redacted).filter((column) => changed[column.key] ?? column.defaultVisible);
}

/** The Flask workflow state of a row for display: an open revision request has its own label and colour. */
export const rowState = (row: { workflow_state: string; revision_requested?: boolean }): string =>
  row.workflow_state === "finalized_upstream_changed" && row.revision_requested ? "sent_back_for_revision" : row.workflow_state;

/** Match a gender chosen from a panel to the spelling the server lists in /filter-options (case-insensitive); "" when none. */
export function matchGender(options: string[], value: string | null): string {
  const wanted = (value ?? "").trim().toLowerCase();
  return options.find((option) => option.trim().toLowerCase() === wanted) ?? "";
}

/**
 * The Data route for a Flask data management link (`/data-management/?project=..&workflow=..`, the Statistics card and
 * row links): the same filters as route params. Null for any other path, which stays a server page.
 */
export function dataRouteForLink(url: string): Record<string, string> | null {
  let parsed: URL;
  try {
    parsed = new URL(url, "http://local.invalid");
  } catch {
    return null;
  }
  if (parsed.origin !== "http://local.invalid" || !/^\/data-management\/?$/.test(parsed.pathname)) return null;
  const params: Record<string, string> = {};
  for (const key of FILTER_KEYS) {
    const value = parsed.searchParams.get(key);
    if (value) params[key] = value;
  }
  return params;
}
