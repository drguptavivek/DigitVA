/**
 * Pure rules of the Statistics view: the URL that names it, the case-list query each tab sends, status folding and
 * count sums. No React, so they are unit-tested directly (__tests__/statistics-logic.test.ts).
 */
import {
  DEFAULT_PERIOD, PERIODS, type AreaProject, type AreaSummary, type CaseListQuery,
  type CaseStatus, type Period, type StageCounts, type StageCountsReply,
} from "../../area/api";
import type { AccessUnit } from "../../api";
import type { StringKey } from "../../i18n";
import { isInternalPlaceholderUnit } from "../../ui/placeholderUnit";

export const TABS = ["overview", "deaths", "interviews", "codings", "projects"] as const;
export type Tab = (typeof TABS)[number];
export type CaseTab = "deaths" | "interviews" | "codings";
export const isCaseTab = (tab: Tab): tab is CaseTab => tab === "deaths" || tab === "interviews" || tab === "codings";

export const SOURCES = ["reported", "direct"] as const;
export type Source = (typeof SOURCES)[number];
/** The server's `source` values: Reported is the death register, Direct is everything entered straight (direct, odk). */
const SOURCE_PARAM: Record<Source, string> = { reported: "register", direct: "direct,odk" };

/** The whole view; `projects` empty means all of the user's projects. */
export interface StatsView {
  tab: Tab;
  projects: string[];
  period: Period;
  unit: string | null;
  site: string | null;
  /** A chip key of the tab (STATUS_CHIPS), or null for all. */
  status: string | null;
  /** Overdue rows only (Deaths: not interviewed; Interviews and Codings: not coded). */
  overdue: boolean;
  /** Deaths only. */
  source: Source | null;
}

/** One status chip: the combined statuses it folds (docs: .tasks/statistics-operational-dashboards.md, "Status fold"). */
export interface StatusChip { key: string; label: StringKey; statuses: CaseStatus[] }

const INTERVIEWED: CaseStatus[] = ["submitted_awaiting_coding", "in_coding"];
const SUBMITTED: CaseStatus[] = ["submitted_awaiting_coding", "in_coding", "coded", "not_codeable"];

export const STATUS_CHIPS: Record<CaseTab, StatusChip[]> = {
  deaths: [
    { key: "pending", label: "statsChipPending", statuses: ["reported", "interview_pending", "interview_in_progress"] },
    { key: "interviewed", label: "statsChipInterviewed", statuses: INTERVIEWED },
    { key: "coded", label: "statsChipCoded", statuses: ["coded"] },
    { key: "refused", label: "statsChipRefused", statuses: ["refused"] },
    { key: "not_codeable", label: "statsChipNotCodeable", statuses: ["not_codeable"] },
  ],
  interviews: [
    { key: "awaiting", label: "statsChipAwaitingCoding", statuses: ["submitted_awaiting_coding"] },
    { key: "in_coding", label: "statsChipInCoding", statuses: ["in_coding"] },
    { key: "coded", label: "statsChipCoded", statuses: ["coded"] },
    { key: "not_codeable", label: "statsChipNotCodeable", statuses: ["not_codeable"] },
    // Consent refused at the interview; the tab sends `interviewed`, so a death refused before any interview is not here.
    { key: "refused", label: "statsChipRefused", statuses: ["refused"] },
  ],
  codings: [
    { key: "not_started", label: "statsChipNotStarted", statuses: ["submitted_awaiting_coding"] },
    { key: "in_coding", label: "statsChipInCoding", statuses: ["in_coding"] },
    { key: "coded", label: "statsChipCoded", statuses: ["coded"] },
    { key: "not_codeable", label: "statsChipNotCodeable", statuses: ["not_codeable"] },
  ],
};

/** What the "All" chip covers: the union of the tab's chips. */
export const allStatuses = (tab: CaseTab): CaseStatus[] => STATUS_CHIPS[tab].flatMap((chip) => chip.statuses);

/** The server's `overdue` value for a tab: deaths wait for an interview, interviews for coding. */
export const OVERDUE_KIND: Record<CaseTab, "interview" | "coding"> = { deaths: "interview", interviews: "coding", codings: "coding" };

type RawParam = string | string[] | undefined;
const MAX_PARAM = 64;
const one = (value: RawParam): string => ((Array.isArray(value) ? value[0] : value) ?? "").trim();
const valid = (value: string) => (value && value.length <= MAX_PARAM ? value : null);

/**
 * The view named by the URL, checked against the projects the server listed (the URL is untrusted). `project` may
 * repeat or be a comma list; unknown ids are dropped, and naming every project is the same as All. Unit and site
 * apply only when exactly one project is in view (unit to organization projects, site to sites projects). Status,
 * overdue and source are kept only on the tabs that have them. Null when the user has no project.
 */
export function parseView(
  raw: { tab?: RawParam; project?: RawParam; period?: RawParam; unit?: RawParam; site?: RawParam; status?: RawParam; overdue?: RawParam; source?: RawParam },
  all: Pick<AreaProject, "project_id" | "mode">[],
): StatsView | null {
  if (all.length === 0) return null;
  const tabText = one(raw.tab);
  const tab: Tab = (TABS as readonly string[]).includes(tabText) ? (tabText as Tab) : "overview";
  const named = new Set((Array.isArray(raw.project) ? raw.project : [raw.project ?? ""]).flatMap((value) => value.split(",")).map((value) => value.trim()));
  const known = all.filter((row) => named.has(row.project_id));
  const projects = known.length === all.length ? [] : known.map((row) => row.project_id);
  const sole = projects.length === 1 ? known[0] : all.length === 1 ? all[0] : null;
  const periodText = one(raw.period);
  const caseTab = isCaseTab(tab) ? tab : null;
  const statusText = one(raw.status);
  const sourceText = one(raw.source);
  return {
    tab,
    projects,
    period: (PERIODS as readonly string[]).includes(periodText) ? (periodText as Period) : DEFAULT_PERIOD,
    unit: sole?.mode === "organization" ? valid(one(raw.unit)) : null,
    site: sole?.mode === "sites" ? valid(one(raw.site)) : null,
    status: caseTab && STATUS_CHIPS[caseTab].some((chip) => chip.key === statusText) ? statusText : null,
    overdue: caseTab !== null && one(raw.overdue) === OVERDUE_KIND[caseTab],
    source: tab === "deaths" && (SOURCES as readonly string[]).includes(sourceText) ? (sourceText as Source) : null,
  };
}

/** URL params of a view; defaults and empty values are left out so links stay short. */
export function viewParams(view: StatsView): Record<string, string> {
  const caseTab = isCaseTab(view.tab) ? view.tab : null;
  return {
    ...(view.tab !== "overview" ? { tab: view.tab } : {}),
    ...(view.projects.length ? { project: view.projects.join(",") } : {}),
    ...(view.period !== DEFAULT_PERIOD ? { period: view.period } : {}),
    ...(view.unit ? { unit: view.unit } : {}),
    ...(view.site ? { site: view.site } : {}),
    ...(caseTab && view.status ? { status: view.status } : {}),
    ...(caseTab && view.overdue ? { overdue: OVERDUE_KIND[caseTab] } : {}),
    ...(view.tab === "deaths" && view.source ? { source: view.source } : {}),
  };
}

/** The view after a tab change: the tab's own filters are dropped, project, period and area stay. */
export const withTab = (view: StatsView, tab: Tab): StatsView => ({ ...view, tab, status: null, overdue: false, source: null });

/** Project ids in view: the chosen ones, or every project for All. */
export const projectsInView = (view: StatsView, all: Pick<AreaProject, "project_id">[]): string[] =>
  (view.projects.length ? view.projects : all.map((row) => row.project_id));

/** Start of a period as a UTC date (the server's `period_start` is UTC midnight); null for all time. */
export function periodStart(period: Period, now: Date): string | null {
  const days = { "30d": 30, "90d": 90, "12m": 365, all: null }[period];
  if (days === null) return null;
  return new Date(now.getTime() - days * 86_400_000).toISOString().slice(0, 10);
}

/**
 * The GET /api/v1/cases query of a case tab. The Interviews and Codings presets default to their own work lists, so
 * those tabs always send their statuses. An overdue list is live, like its count, so it carries no period. Every tab
 * asks for the submissions with no register row too (`unregistered`), so a project without a death register is listed;
 * Interviews and Codings list only cases with a submission (`interviewed`). The Overview's numbers (stage-counts) are
 * these tabs' totals.
 */
export function casesQuery(view: StatsView & { tab: CaseTab }, projectIds: string[], now: Date, cursor: string | null): CaseListQuery {
  const chip = STATUS_CHIPS[view.tab].find((one) => one.key === view.status);
  const statuses = chip ? chip.statuses : view.tab === "deaths" ? null : allStatuses(view.tab);
  const since = view.overdue ? null : periodStart(view.period, now);
  return {
    preset: { deaths: "deaths", interviews: "interview", codings: "coding" }[view.tab],
    project_id: projectIds.join(","),
    status: statuses ? statuses.join(",") : null,
    [view.tab === "deaths" ? "reported_from" : "submitted_from"]: since,
    source: view.tab === "deaths" && view.source ? SOURCE_PARAM[view.source] : null,
    org_unit_id: view.unit,
    site_id: view.site,
    overdue: view.overdue ? OVERDUE_KIND[view.tab] : null,
    unregistered: "1",
    interviewed: view.tab === "deaths" ? null : "1",
    limit: "50",
    cursor,
  };
}

/** A chip's number: its statuses summed from the page counts; All is the tab's statuses. */
export function chipCount(counts: Record<string, number> | undefined, statuses: CaseStatus[]): number {
  return statuses.reduce((sum, status) => sum + (counts?.[status] ?? 0), 0);
}

/**
 * The GET /api/v1/cases/stage-counts query of the Overview (*projectIds* in view, the area of one) or the Projects tab
 * (every project, no area): the same project, area and period the case tabs send, so each number is a tab's total.
 */
export function stageCountsQuery(projectIds: string[], area: { unit: string | null; site: string | null }, period: Period, now: Date): CaseListQuery {
  const since = periodStart(period, now);
  return { project_id: projectIds.join(","), org_unit_id: area.unit, site_id: area.site, reported_from: since, submitted_from: since };
}

export const NO_STAGES: StageCounts = { reported: 0, interviewed: 0, coded: 0, overdue_interview: 0, overdue_coding: 0 };

/** One project's numbers; a project the server left out has nothing in reach. */
export const projectStages = (reply: StageCountsReply, projectId: string): StageCounts => reply.projects[projectId] ?? NO_STAGES;

/** Whole days from one server stamp to another (Days to code); null when either is missing or unreadable. */
export function daysBetween(from: string | null | undefined, to: string | null | undefined): number | null {
  if (!from || !to) return null;
  const start = Date.parse(from);
  const end = Date.parse(to);
  return Number.isNaN(start) || Number.isNaN(end) ? null : Math.max(0, Math.floor((end - start) / 86_400_000));
}

/**
 * The Area drop-down of one project's summary: All areas (unless the user's area is one root, opened at once), the
 * path to the current unit, then the units or sites that open below it. `depth` indents the label.
 */
export function areaOptions(
  summary: Pick<AreaSummary, "mode" | "breadcrumb" | "rows">,
  soleRoot: string | null,
  units?: Pick<AccessUnit, "org_unit_id" | "unit_name" | "path" | "is_active">[],
): { value: string; kind: "unit" | "site" | "all"; name: string; depth: number }[] {
  const path = summary.breadcrumb.map((crumb, index) => ({ value: crumb.org_unit_id, kind: "unit" as const, name: crumb.name, depth: index }));
  // Case tabs pass the user's own units (already in the bootstrap): every unit under the current one, leaves included.
  const here = units?.find((unit) => unit.org_unit_id === summary.breadcrumb.at(-1)?.org_unit_id);
  const under = (units ?? []).filter((unit) => unit.is_active && !isInternalPlaceholderUnit(unit.unit_name) && (!here || unit.path.startsWith(`${here.path}.`)));
  const segments = (unit: { path: string }) => unit.path.split(".").length;
  const top = Math.min(...under.map(segments));
  const deep = summary.mode === "organization" && units
    ? under.sort((a, b) => a.path.localeCompare(b.path)).map((unit) => ({
      value: unit.org_unit_id, kind: "unit" as const, name: unit.unit_name,
      depth: path.length + segments(unit) - (here ? segments(here) + 1 : top),
    }))
    : null;
  const below = (deep ?? summary.rows
    .filter((row) => row.kind === "site" || (row.kind === "unit" && row.has_children))
    .map((row) => ({ value: row.key, kind: row.kind === "site" ? "site" as const : "unit" as const, name: row.name, depth: path.length })))
    .filter((option) => !path.some((crumb) => crumb.value === option.value));
  return [...(soleRoot ? [] : [{ value: "", kind: "all" as const, name: "", depth: 0 }]), ...path, ...below];
}

/**
 * The project choice after one checkbox press: from All, a project narrows to that one; otherwise it toggles.
 * No project left, or every project, is All (empty).
 */
export function toggleProject(chosen: string[], id: string, allIds: string[]): string[] {
  const next = chosen.length === 0 ? [id] : chosen.includes(id) ? chosen.filter((one) => one !== id) : [...chosen, id];
  const ordered = allIds.filter((one) => next.includes(one));
  return ordered.length === allIds.length ? [] : ordered;
}

/** Most summary requests in flight at once, so a dozen projects do not hammer the server. */
export const MAX_SUMMARY_REQUESTS = 4;

/** One project's summary request: the answer once in, the error text if it failed, *fetching* while a request is out. */
export interface ProjectLoad { summary: AreaSummary | null; error: string; fetching: boolean }

/** The summaries that have arrived, in *ids* order. */
export const loadedSummaries = (ids: string[], byId: Record<string, ProjectLoad | undefined>): AreaSummary[] =>
  ids.flatMap((id) => byId[id]?.summary ?? []);

/** Projects still waiting (no answer, no error) and the ids of those that failed. */
export function loadCounts(ids: string[], byId: Record<string, ProjectLoad | undefined>): { pending: number; failedIds: string[] } {
  const failedIds = ids.filter((id) => !byId[id]?.summary && byId[id]?.error);
  return { pending: ids.filter((id) => !byId[id]?.summary && !byId[id]?.error).length, failedIds };
}

/** Runs *task* for every id with at most *limit* in flight, starting them in order; resolves when all are done. */
export async function runLimited(ids: string[], limit: number, task: (id: string) => Promise<void>): Promise<void> {
  const queue = [...ids];
  const worker = async () => {
    for (let id = queue.shift(); id !== undefined; id = queue.shift()) await task(id);
  };
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, worker));
}
