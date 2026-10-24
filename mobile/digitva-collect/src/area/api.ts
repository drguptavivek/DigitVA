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
