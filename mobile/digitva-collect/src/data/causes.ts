/**
 * Pure rules of the Data screen's Causes tab: the URL <-> filter mapping (the URL names, mapped to the API's
 * `project_id` / `site_id`), and the shaping of the aggregates payload into the rows the tab draws. No React.
 * The URL is untrusted: every value is checked here, and the server scopes every number anyway.
 */
import type { CodAgeSex, CodAggregates, CodRow, CodUnmatchedIcd, DmParams } from "./api";

export const CAUSES_KEYS = ["scheme_code", "project", "site", "form_id", "gender", "date_from", "date_to", "age"] as const;
export type CausesKey = (typeof CAUSES_KEYS)[number];
export type CausesQuery = Record<CausesKey, string>;

type RawParam = string | string[] | undefined;
const one = (value: RawParam): string => ((Array.isArray(value) ? value[0] : value) ?? "").trim();
const TOKEN = /^[\w.\-]{1,64}$/;
// Dates are only shape-checked: a bad one goes to the server, which answers 400 invalid_date and the tab says so.
const DATE_TEXT = /^[\w\-./]{1,20}$/;
const token = (value: string) => (TOKEN.test(value) ? value : "");

export function parseCausesQuery(raw: Partial<Record<string, RawParam>>): CausesQuery {
  return {
    scheme_code: token(one(raw.scheme_code)),
    project: token(one(raw.project)),
    site: token(one(raw.site)),
    form_id: token(one(raw.form_id)),
    gender: token(one(raw.gender).slice(0, 40)),
    date_from: DATE_TEXT.test(one(raw.date_from)) ? one(raw.date_from) : "",
    date_to: DATE_TEXT.test(one(raw.date_to)) ? one(raw.date_to) : "",
    // Only ever compared with the payload's own age filter keys ("0-<28 days"), never sent to the server.
    age: one(raw.age).slice(0, 60),
  };
}

/** Every Causes URL key with its value, `undefined` when empty (router.setParams merges, so an omitted key would linger). */
export const causesPatch = (query: CausesQuery): Record<string, string | undefined> =>
  Object.fromEntries(CAUSES_KEYS.map((key) => [key, query[key] || undefined]));

/** The aggregates and export filters, with the API's names. The age choice is a view of the payload, not a filter. */
export function causesApiParams(query: CausesQuery): DmParams {
  const params: DmParams = {};
  const map: [CausesKey, string][] = [
    ["scheme_code", "scheme_code"], ["project", "project_id"], ["site", "site_id"], ["form_id", "form_id"],
    ["gender", "gender"], ["date_from", "date_from"], ["date_to", "date_to"],
  ];
  for (const [from, to] of map) if (query[from]) params[to] = query[from];
  return params;
}

/** The age filter key to show: the one in the URL when the payload offers it, else "all". */
export const ageKey = (age: string, filters: { key: string }[]): string => (filters.some((filter) => filter.key === age) ? age : "all");

export const topCausesFor = (summary: CodAggregates["summary"], age: string) =>
  (age !== "all" && summary.top_causes_by_age?.[age]) || summary.top_causes || [];
export const groupsFor = (summary: CodAggregates["summary"], age: string) =>
  (age !== "all" && summary.first_level_counts_by_age?.[age]) || summary.first_level_counts || [];

export interface Counts { male: number; female: number; unknown: number; total: number }
export interface CauseNode extends Counts { key: string; label: string; level: 0 | 1 | 2; children: CauseNode[] }
export interface ScopeSection extends Counts {
  key: string;
  label: string;
  tree: CauseNode[];
  /** Coded deaths of this scope that matched no category. */
  unmatched: number;
  dropped: CodUnmatchedIcd[];
}

const NONE = "__none__";
const scopeKey = (value: string | null | undefined) => (value ? String(value) : NONE);
const text = (value: string | null | undefined) => (value && String(value).trim() ? String(value).trim() : "Unknown");
const add = (into: Counts, row: CodRow) => {
  into.male += row.male_count || 0;
  into.female += row.female_count || 0;
  into.unknown += row.unknown_count || 0;
  into.total += row.coded_count || 0;
};
const zero = (): Counts => ({ male: 0, female: 0, unknown: 0, total: 0 });

/** One age scope's rows as category > (subcategory >) disease nodes, in first-seen order, counts summed upward. */
export function buildTree(rows: CodRow[]): CauseNode[] {
  const roots = new Map<string, CauseNode>();
  for (const row of rows) {
    const category = text(row.bucket_category);
    let root = roots.get(category);
    if (!root) roots.set(category, (root = { key: category, label: category, level: 0, children: [], ...zero() }));
    add(root, row);
    let parent = root;
    if (row.bucket_subcategory) {
      const sub = text(row.bucket_subcategory);
      let node = parent.children.find((child) => child.level === 1 && child.label === sub);
      if (!node) parent.children.push((node = { key: `${category}/${sub}`, label: sub, level: 1, children: [], ...zero() }));
      add(node, row);
      parent = node;
    }
    parent.children.push({ key: `${parent.key}/${parent.children.length}`, label: text(row.bucket_field), level: 2, children: [], male: row.male_count || 0, female: row.female_count || 0, unknown: row.unknown_count || 0, total: row.coded_count || 0 });
  }
  return [...roots.values()];
}

/** The per-age-scope sections: matched rows as a tree plus the unmatched count and ICD rows; All ages first, then by sort order. */
export function scopeSections(data: CodAggregates): ScopeSection[] {
  const byScope = new Map<string, { label: string; order: number; rows: CodRow[] }>();
  const ensure = (scope: string | null, label?: string | null, order?: number | null) => {
    const key = scopeKey(scope);
    let entry = byScope.get(key);
    if (!entry) byScope.set(key, (entry = { label: label || (key === NONE ? "All ages" : key), order: Number(order || (key === NONE ? 1 : 999)), rows: [] }));
    return entry;
  };
  for (const row of data.data ?? []) ensure(row.age_scope, row.age_scope_label, row.age_scope_sort_order).rows.push(row);
  for (const row of data.summary?.unmatched_by_age_scope ?? []) ensure(row.age_scope, row.age_scope_label, row.age_scope_sort_order);
  const unmatched = new Map((data.summary?.unmatched_by_age_scope ?? []).map((row) => [scopeKey(row.age_scope), row.unmatched_count || 0]));
  return [...byScope.entries()]
    .sort(([a, x], [b, y]) => (a === NONE ? -1 : b === NONE ? 1 : x.order - y.order || x.label.localeCompare(y.label)))
    .map(([key, entry]) => {
      const sums = zero();
      entry.rows.forEach((row) => add(sums, row));
      return {
        key, label: entry.label, ...sums, tree: buildTree(entry.rows), unmatched: unmatched.get(key) || 0,
        dropped: (data.summary?.unmatched_icd_breakdown ?? []).filter((row) => scopeKey(row.age_scope) === key),
      };
    });
}

/** Age and sex rows plus the column totals for the table's last line. */
export function ageSexTotals(rows: CodAgeSex[]): Counts {
  return rows.reduce((sum, row) => ({
    male: sum.male + (row.male_count || 0), female: sum.female + (row.female_count || 0),
    unknown: sum.unknown + (row.unknown_count || 0), total: sum.total + (row.total_count || 0),
  }), zero());
}

/** The server's refusal codes the tab words itself (400); anything else is left to the generic error text. */
export const CAUSES_ERROR_CODES = ["invalid_date", "unknown_scheme", "no_active_scheme"] as const;
