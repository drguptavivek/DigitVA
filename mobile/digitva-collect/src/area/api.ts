/** Area dashboard (Statistics) calls over the browser session, through the shared JSON requester. GET only. */
import type { JsonRequester } from "../workspace/api";

const AREA_API = "/api/v1/area";

export const PERIODS = ["30d", "90d", "12m", "all"] as const;
export type Period = (typeof PERIODS)[number];
export const DEFAULT_PERIOD: Period = "all";

/** Every count of a row and of the area card (app/services/area_dashboard_service.py COUNT_KEYS). */
export interface AreaCounts {
  deaths_reported: number;
  deaths_7_days: number;
  deaths_30_days: number;
  interviews_pending: number;
  pending_over_7_days: number;
  pending_over_30_days: number;
  submitted: number;
  awaiting_coding: number;
  not_codeable: number;
  final_cod: number;
  smartva_failed: number;
  visit_notes: number;
  /** Live, period-independent: deaths not interviewed after `thresholds.interview_days`. Optional until every server sends it. */
  overdue_interview?: number;
  /** Live, period-independent: interviews not coded after `thresholds.coding_days`. */
  overdue_coding?: number;
}

export interface AreaProject {
  project_id: string;
  project_name: string;
  mode: "organization" | "sites";
  project_wide: boolean;
  roots: { key: string; code: string; name: string }[];
}

/** `unit` rows drill down by `key` (the org unit id); `site` and `unrouted` rows do not. */
export interface AreaRow {
  kind: "unit" | "site" | "unrouted";
  key: string;
  code: string | null;
  name: string;
  has_children: boolean;
  counts: AreaCounts;
  /** Count key -> server URL, present only for screens the viewer's role has. */
  links?: Record<string, string>;
}

export interface AreaCause {
  /** The server's English label; the app names the folded row itself, by `suppressed`. */
  label: string;
  /** True only on the folded "Other" row (small causes, beyond the top ten, unmapped codes). */
  suppressed: boolean;
  coded_count: number;
  percent: number;
}

export interface AreaCauses {
  coded: number;
  /** True when fewer than 20 deaths are coded: no rows are sent. */
  hidden: boolean;
  rows: AreaCause[];
}

export interface AreaStations {
  active: number;
  never_synced: number;
  oldest_last_bundle_at_display: string | null;
  latest_bundle_at_display: string | null;
}

export interface AreaSummary {
  project_id: string;
  project_name: string;
  mode: "organization" | "sites";
  project_wide: boolean;
  period: Period;
  unit: { org_unit_id: string; code: string; name: string } | null;
  breadcrumb: { org_unit_id: string; code: string; name: string }[];
  card: {
    counts: AreaCounts;
    medians: {
      death_to_interview_days: number | null;
      death_to_interview_n: number;
      interview_to_final_cod_days: number | null;
      interview_to_final_cod_n: number;
    };
    causes: AreaCauses;
    links: Record<string, string>;
  };
  rows: AreaRow[];
  project_card: { stations: AreaStations } | null;
  freshness: {
    snapshot_refreshed_at: string | null;
    snapshot_refreshed_display: string | null;
    live_at_display: string | null;
  };
  /** The overdue cut-offs in days (server constants). */
  thresholds?: { interview_days: number; coding_days: number };
}

export interface AreaInterviewer {
  name: string;
  cases_registered: number;
  interviews_started: number;
  submitted: number;
  in_progress: number;
  contact_attempts_30_days: number;
}

export interface AreaStaff {
  project_id: string;
  staff_identity_redacted: boolean;
  interviewers: AreaInterviewer[];
  truncated: boolean;
}

export interface AreaQuery {
  project: string;
  unit?: string | null;
  /** A sites-mode site; exclusive with `unit`. */
  site?: string | null;
  period?: Period;
}

function query(params: Record<string, string | null | undefined>): string {
  const pairs = Object.entries(params).filter(([, value]) => value);
  return pairs.length ? `?${pairs.map(([key, value]) => `${key}=${encodeURIComponent(value!)}`).join("&")}` : "";
}

export async function getAreaProjects(request: JsonRequester): Promise<AreaProject[]> {
  const reply = (await request(`${AREA_API}/projects`)) as { projects: AreaProject[] };
  return reply.projects;
}

export function getAreaSummary(request: JsonRequester, { project, unit, site, period = DEFAULT_PERIOD }: AreaQuery): Promise<AreaSummary> {
  return request(`${AREA_API}/summary${query({ project, unit, site, period })}`) as Promise<AreaSummary>;
}

export function getAreaStaff(request: JsonRequester, { project, unit, site }: AreaQuery): Promise<AreaStaff> {
  return request(`${AREA_API}/staff${query({ project, unit, site })}`) as Promise<AreaStaff>;
}

/** The same level as the summary, as a spreadsheet download: a plain URL, no request. */
export function areaCsvUrl({ project, unit, site, period = DEFAULT_PERIOD }: AreaQuery): string {
  return `${AREA_API}/summary${query({ project, unit, site, period, format: "csv" })}`;
}

/** Combined case status (app/services/case_list_service.py COMBINED_STATUSES). */
export type CaseStatus =
  | "reported" | "interview_pending" | "interview_in_progress" | "submitted_awaiting_coding" | "in_coding"
  | "coded" | "refused" | "not_codeable" | "duplicate" | "cancelled";

/**
 * One GET /api/v1/cases row. A field the caller may not see is absent, not blank: `deceased_name` (personal-data
 * gate), `reporter_name` / `interviewer_name` / `coder_name` (staff-identity gate), `unit_name` (unit reach).
 * With `unregistered=1`, a submission no register row names has `death_id` null and always its `va_sid`.
 */
export interface CaseListRow {
  death_id: string | null;
  unique_id: string;
  project_id: string;
  site_id: string;
  status: CaseStatus;
  source: string;
  age_years: number | null;
  deceased_sex: string | null;
  date_of_death: string | null;
  created_at: string;
  deceased_name?: string | null;
  /** False where the caller may see the name and none is recorded; absent wherever the name is hidden. */
  name_recorded?: false;
  unit_name?: string | null;
  reporter_name?: string | null;
  interviewer_name?: string | null;
  coder_name?: string | null;
  submitted_at?: string | null;
  coded_at?: string | null;
  overdue?: "interview" | "coding" | null;
  days_waiting?: number | null;
  /** True when the caller may view the row's submission; `va_sid` comes with it. */
  can_open?: boolean;
  va_sid?: string;
}

export interface CaseListPage {
  cases: CaseListRow[];
  /** Rows per combined status (plus `total`), ignoring the status filter; first page only. */
  counts?: Record<string, number>;
  next_cursor: string | null;
}

/** GET /api/v1/cases query; `project_id` is a comma list, absent values are left out. */
export type CaseListQuery = Record<string, string | null | undefined>;

/** Check the server-owned page shape before the screen uses it; a malformed reply is an error, not a blank table. */
export function parseCaseListPage(value: unknown): CaseListPage {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const ok = record(value) && Array.isArray(value.cases) && (value.next_cursor === null || typeof value.next_cursor === "string") &&
    (value.counts === undefined || record(value.counts)) &&
    value.cases.every((row) => record(row) && (typeof row.death_id === "string" || (row.death_id === null && typeof row.va_sid === "string")) &&
      typeof row.unique_id === "string" && typeof row.status === "string");
  if (!ok) throw new Error("malformed_response");
  return value as unknown as CaseListPage;
}

export async function listCases(request: JsonRequester, params: CaseListQuery): Promise<CaseListPage> {
  return parseCaseListPage(await request(`/api/v1/cases${query(params)}`));
}

/** The Statistics stage and overdue numbers of one project, or summed; each equals a case tab's total. */
export interface StageCounts {
  reported: number;
  interviewed: number;
  coded: number;
  overdue_interview: number;
  overdue_coding: number;
}

/** GET /api/v1/cases/stage-counts: per project (absent when nothing is in reach), the total and the overdue thresholds. */
export interface StageCountsReply {
  projects: Record<string, StageCounts>;
  total: StageCounts;
  thresholds: { interview_days: number; coding_days: number };
}

const STAGE_KEYS: (keyof StageCounts)[] = ["reported", "interviewed", "coded", "overdue_interview", "overdue_coding"];

/** Check the reply's shape: every number present, so a missing one is an error rather than a wrong zero. */
export function parseStageCounts(value: unknown): StageCountsReply {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const counts = (item: unknown) => record(item) && STAGE_KEYS.every((key) => typeof item[key] === "number");
  const ok = record(value) && record(value.projects) && Object.values(value.projects).every(counts) && counts(value.total) &&
    record(value.thresholds) && typeof value.thresholds.interview_days === "number" && typeof value.thresholds.coding_days === "number";
  if (!ok) throw new Error("malformed_response");
  return value as unknown as StageCountsReply;
}

export async function getStageCounts(request: JsonRequester, params: CaseListQuery): Promise<StageCountsReply> {
  return parseStageCounts(await request(`/api/v1/cases/stage-counts${query(params)}`));
}
