/**
 * Data (data manager overview) calls over the browser session, through the shared JSON requester.
 * GETs read /api/v1/data-management/* and /api/v1/analytics/*; the POSTs carry the CSRF token the transport adds.
 * Exports are plain URLs for a navigation or an anchor, never a request: the server may answer with a redirect to S3.
 */
import type { JsonRequester } from "../workspace/api";

const DM_API = "/api/v1/data-management";
const ANALYTICS_API = "/api/v1/analytics";

/** The ten filters the lists and counts share, with the names the API and the Flask page use. */
export type DmParams = Record<string, string>;

export interface DmKpi {
  total_submissions: number;
  coded_submissions: number;
  pending_submissions: number;
  smartva_pending_submissions: number;
  flagged_submissions: number;
  odk_has_issues_submissions: number;
  smartva_missing_submissions: number;
  smartva_failed_submissions: number;
  revoked_submissions: number;
  not_analysable_submissions: number;
  not_analysable_by_reason: { refused?: number; respondent_unavailable?: number; partially_completed?: number };
  missing_in_odk_submissions: number;
  /** Effective state (an open revision request reads as sent_back_for_revision) -> count. */
  workflow_counts: Record<string, number>;
}

export interface DmVisitNote {
  date?: string | null;
  address?: string | null;
  remarks?: string | null;
  redacted?: boolean;
}

export interface DmSubmissionRow {
  va_sid: string;
  va_uniqueid_masked: string | null;
  project_id: string;
  site_id: string;
  /** "web" for a phone or web interview (no ODK review state, sync or edit page); "odk" or absent (older server) otherwise. */
  form_source?: "odk" | "web";
  va_submission_date: string | null;
  /** Null for a redacted viewer. */
  va_data_collector: string | null;
  attachment_count: number;
  has_smartva: boolean;
  has_smartva_failed: boolean;
  va_odk_reviewstate: string | null;
  va_odk_reviewcomments: { body?: string }[] | null;
  workflow_state: string;
  va_dmreview_createdat: string | null;
  analytics_age_band: string | null;
  va_deceased_gender: string | null;
  va_consent: string | null;
  coded_on: string | null;
  /** Null for a redacted viewer. */
  coded_by: string | null;
  visit_note: DmVisitNote | null;
  revision_requested: boolean;
  odk_sync_status: "in_sync" | "missing_in_odk";
}

export interface DmSubmissionsPage {
  data: DmSubmissionRow[];
  page: number;
  size: number;
  returned_count: number;
  has_more: boolean;
  last_page: number;
  total: number;
}

export interface DmFilterOptions {
  projects: string[];
  sites: { project_id: string; site_id: string }[];
  genders: string[];
}

export interface DmCoderDaily {
  dates: { iso: string; label: string; is_today: boolean }[];
  rows: { coder_name: string | null; daily: Record<string, number>; window_total: number; cumulative_total: number }[];
  timezone: string;
  window_days: number;
  staff_identity_redacted?: boolean;
}

export interface DmSiteStat {
  project_id: string;
  site_id: string;
  total_submissions: number;
  this_week_submissions: number;
  today_submissions: number;
}

export interface DmUnitStat {
  org_unit_id: string;
  org_unit_code: string;
  org_unit_name: string;
  total_submissions: number;
}

export type DmSiteSubmissions =
  | { group_by: "site"; stats: DmSiteStat[]; timezone: string }
  | { group_by: "org_unit"; stats: DmUnitStat[]; timezone: string };

export interface DmDemographics {
  age_bands: { band: string | null; count: number }[];
  sex: { sex: string | null; count: number }[];
}

export interface UpstreamField {
  field_id: string;
  field_label: string | null;
  category_code: string | null;
  subcategory_code: string | null;
  previous_value_display: string;
  current_value_display: string;
}

export interface UpstreamChangeDetails {
  va_sid: string;
  changed_fields: UpstreamField[];
  formatting_only_changed_fields: UpstreamField[];
  non_substantive_changed_fields: UpstreamField[];
  pii_changed: boolean;
}

export type ExportKind = "data" | "coded_cod_snapshot" | "smartva_input" | "smartva_results" | "smartva_likelihoods";

const EXPORT_PATHS: Record<ExportKind, string> = {
  data: "submissions/export.csv",
  coded_cod_snapshot: "submissions/export-coded-cod-snapshot.csv",
  smartva_input: "submissions/export-smartva-input.csv",
  smartva_results: "submissions/export-smartva-results.csv",
  smartva_likelihoods: "submissions/export-smartva-likelihoods.csv",
};
export const EXPORT_KINDS = Object.keys(EXPORT_PATHS) as ExportKind[];

/** `?a=1&b=2` of the non-empty values, encoded; the bracketed sort names survive (`sort[0][field]`). */
export function dmQuery(params: DmParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value) search.set(key, value);
  const text = search.toString();
  return text ? `?${text}` : "";
}

const sid = (value: string) => encodeURIComponent(value);

export const getDmKpi = (request: JsonRequester, params: DmParams) =>
  request(`${DM_API}/kpi${dmQuery(params)}`) as Promise<DmKpi>;
export const getDmSubmissions = (request: JsonRequester, params: DmParams) =>
  request(`${DM_API}/submissions${dmQuery(params)}`) as Promise<DmSubmissionsPage>;
export const getDmFilterOptions = (request: JsonRequester) =>
  request(`${DM_API}/filter-options`) as Promise<DmFilterOptions>;
export const getDmCoderDaily = (request: JsonRequester, params: DmParams) =>
  request(`${DM_API}/coder-daily-stats${dmQuery(params)}`) as Promise<DmCoderDaily>;
export const getDmSiteSubmissions = (request: JsonRequester, params: DmParams) =>
  request(`${DM_API}/project-site-submissions${dmQuery(params)}`) as Promise<DmSiteSubmissions>;
export const getDmDemographics = (request: JsonRequester, params: DmParams) =>
  request(`${ANALYTICS_API}/demographics${dmQuery(params)}`) as Promise<DmDemographics>;
export const getUpstreamChangeDetails = (request: JsonRequester, vaSid: string) =>
  request(`${DM_API}/submissions/${sid(vaSid)}/upstream-change-details`) as Promise<UpstreamChangeDetails>;

/** Rebuild the analytics views the cards read (5 a minute per user). */
export const refreshDmAnalytics = (request: JsonRequester) =>
  request(`${ANALYTICS_API}/mv/refresh`, { method: "POST" });
export const acceptUpstreamChange = (request: JsonRequester, vaSid: string) =>
  request(`${DM_API}/submissions/${sid(vaSid)}/accept-upstream-change`, { method: "POST" });
export const rejectUpstreamChange = (request: JsonRequester, vaSid: string) =>
  request(`${DM_API}/submissions/${sid(vaSid)}/reject-upstream-change`, { method: "POST" });
export const cancelRevisionRequest = (request: JsonRequester, vaSid: string) =>
  request(`${DM_API}/submissions/${sid(vaSid)}/cancel-revision-request`, { method: "POST" });

/** A CSV download as a plain URL (navigate or anchor); *params* are the export filters. */
export function dmExportUrl(kind: ExportKind, params: DmParams): string {
  return `${DM_API}/${EXPORT_PATHS[kind]}${dmQuery(params)}`;
}

const COD_API = "/api/v1/cod-buckets";

export interface CodScheme {
  scheme_code: string;
  scheme_name: string;
  mapping_version?: string | null;
  is_active: boolean;
}

/** One coded-death count of a scheme category/subcategory/disease within an age scope. */
export interface CodRow {
  age_scope: string | null;
  age_scope_label?: string | null;
  age_scope_sort_order?: number | null;
  bucket_category: string | null;
  bucket_subcategory: string | null;
  bucket_field: string | null;
  coded_count: number;
  male_count: number;
  female_count: number;
  unknown_count: number;
}

export interface CodTopCause { rank: number; display_label: string; coded_count: number; percent: number }
export interface CodGroup { label: string; coded_count: number; percent: number }
export interface CodAgeSex { age_band: string; male_count: number; female_count: number; unknown_count: number; total_count: number; total_percent: number }
export interface CodUnmatchedScope { age_scope: string | null; age_scope_label?: string | null; age_scope_sort_order?: number | null; unmatched_count: number }
export interface CodUnmatchedIcd { age_scope: string | null; category: string; icd_code: string | null; unmatched_count: number }

/** The parts of the aggregates payload the screen reads; heatmap, treemap and the gender split are left for later. */
export interface CodAggregates {
  filters?: { scheme_code?: string };
  data: CodRow[];
  summary: {
    scheme_used: string;
    matched_total: number;
    top_causes: CodTopCause[];
    top_causes_by_age: Record<string, CodTopCause[]>;
    first_level_counts: CodGroup[];
    first_level_counts_by_age: Record<string, CodGroup[]>;
    age_filters: { key: string; label: string }[];
    age_sex_distribution: CodAgeSex[];
    unmatched_by_age_scope: CodUnmatchedScope[];
    unmatched_icd_breakdown: CodUnmatchedIcd[];
  };
}

export const getCodSchemes = (request: JsonRequester) =>
  request(`${COD_API}/schemes`) as Promise<{ data: CodScheme[] }>;
export const getCodAggregates = (request: JsonRequester, params: DmParams) =>
  request(`${COD_API}/aggregates${dmQuery(params)}`) as Promise<CodAggregates>;

/** The row-level CSV (SID, age, sex, cause) as a plain URL for an anchor; *params* are the aggregates filters. */
export const codExportUrl = (params: DmParams): string => `${COD_API}/export.csv${dmQuery(params)}`;
