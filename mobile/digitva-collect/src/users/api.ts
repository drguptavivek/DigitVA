/** The Users page calls (digitva-75wn) over the browser session, through the shared JSON requester. The server scopes every reply (docs/policy/access-control-model.md, "Users page"). */
import type { OrgProject } from "../organization/api";
import type { JsonRequester } from "../workspace/api";

const USERS_API = "/api/v1/users";

export interface UserGrant {
  role: string;
  scope: "project" | "project_site" | "org_unit";
  project_id: string;
  project_name: string | null;
  site_id: string | null;
  site_name: string | null;
  org_unit_id: string | null;
  unit_name: string | null;
  level_name: string | null;
}

export type EnrolmentState = "enrolled" | "revoked" | "none";

export interface UserEnrolment {
  status: EnrolmentState;
  devices: number;
  revoked_devices: number;
  last_seen_at: string | null;
}

export interface DirectoryUser {
  user_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  active: boolean;
  last_signed_in_at: string | null;
  grants: UserGrant[];
  enrolment: UserEnrolment;
}

export interface DirectoryOptions {
  projects: { project_id: string; project_name: string }[];
  units: { org_unit_id: string; unit_name: string; level_name: string; depth: number }[];
}

export interface UsersPage {
  users: DirectoryUser[];
  total: number;
  limit: number;
  offset: number;
  options?: DirectoryOptions;
}

export interface UserFilters {
  q?: string;
  project?: string;
  unit?: string;
  role?: string;
  status?: "all" | "active" | "inactive";
  enrolment?: EnrolmentState | "";
  /** Account created: today or yesterday (the viewer's day); wins over the from/to pair on the server. */
  created?: "" | "today" | "yesterday";
  created_from?: string;
  created_to?: string;
  email_verified?: YesNo;
  password_set?: YesNo;
  passkey?: YesNo;
}

export type YesNo = "" | "yes" | "no";

export const DEFAULT_FILTERS: UserFilters = {
  q: "", project: "", unit: "", role: "", status: "active", enrolment: "",
  created: "", created_from: "", created_to: "", email_verified: "", password_set: "", passkey: "",
};

const FILTER_KEYS = Object.keys(DEFAULT_FILTERS) as (keyof UserFilters)[];

/** The filters in a URL query string; unknown keys and bad values fall back to the default. */
export function filtersFromSearch(search: string): UserFilters {
  const params = new URLSearchParams(search);
  const out: Record<string, string> = { ...(DEFAULT_FILTERS as Record<string, string>) };
  for (const key of FILTER_KEYS) {
    const value = (params.get(key) ?? "").trim().slice(0, 64);
    if (value) out[key] = value;
  }
  const oneOf = (key: string, allowed: string[], fallback: string) => { if (!allowed.includes(out[key])) out[key] = fallback; };
  oneOf("status", ["all", "active", "inactive"], "active");
  oneOf("enrolment", ["", "enrolled", "revoked", "none"], "");
  oneOf("created", ["", "today", "yesterday"], "");
  for (const key of ["email_verified", "password_set", "passkey"]) oneOf(key, ["", "yes", "no"], "");
  for (const key of ["created_from", "created_to"]) if (!/^\d{4}-\d{2}-\d{2}$/.test(out[key])) out[key] = "";
  return out as UserFilters;
}

/** The query string (no leading "?") for the filters that differ from the default, so a default view has a clean URL. */
export function filtersToSearch(filters: UserFilters): string {
  const params = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const value = (filters[key] ?? "").trim();
    if (value !== (DEFAULT_FILTERS[key] ?? "")) params.set(key, value);
  }
  return params.toString();
}

/** How many fly-out filters are set (everything but the search box; the account filter counts when not the default). */
export function activeFilterCount(filters: UserFilters): number {
  const keys: (keyof UserFilters)[] = ["project", "unit", "role", "enrolment", "created", "email_verified", "password_set", "passkey"];
  let count = keys.filter((key) => (filters[key] ?? "") !== "").length;
  if (filters.status !== "active") count += 1;
  if (!filters.created && (filters.created_from || filters.created_to)) count += 1;
  return count;
}

export type ActivityCounts = {
  deaths_reported: number;
  interviews_submitted: number;
  drafts_in_progress: number;
  coded: number;
  not_codeable: number;
  reviewed: number;
};

export interface UserActivity {
  user_id: string;
  name: string;
  totals: ActivityCounts;
  by_project: Record<string, ActivityCounts>;
  last_signed_in_at: string | null;
  last_device_seen_at: string | null;
  last_active_at: string | null;
}

export interface IssuedCode {
  code: string;
  qr_payload: string;
  qr_png: string;
  project_id: string;
  expires_at: string;
  max_uses: number;
}

/** GET /users/<id>/status: never a password, hash, token or code (docs/current-state/api-v1.md). */
export interface UserStatus {
  user_id: string;
  name: string;
  active: boolean;
  created_at: string | null;
  email_verified: boolean;
  email_verified_at: string | null;
  password_set: boolean;
  verification_email_sent_at: string | null;
  password_emailed_at: string | null;
  terms_accepted: boolean;
  terms_accepted_at: string | null;
  passkeys: { count: number; last_used_at: string | null };
  enrolment_codes: { generated_at: string | null; project_id: string | null; status: "valid" | "used" | "expired" | "revoked" | "unknown"; expires_at: string | null }[];
  mobile: UserEnrolment;
  sign_in_qrs: SignInQrItem[];
  training: { session_code: string; session_name: string | null; session_status: string | null; role: string | null; coder_slot: string | number | null; onboarded: boolean; onboarded_at: string | null }[];
}

export interface SignInQrItem {
  status: "pending" | "expired" | "redeemed" | "revoked";
  issued_at: string | null;
  expires_at: string | null;
  redeemed_at: string | null;
}

export interface SignInQrShown {
  code: string;
  qr_payload: string;
  qr_png: string;
  expires_at: string;
}

export async function getUserStatus(request: JsonRequester, userId: string): Promise<UserStatus> {
  return (await request(`${USERS_API}/${encodeURIComponent(userId)}/status`)) as UserStatus;
}

/** GET /users/<id>/placement: "My organization"'s projects for that user, cut to the viewer's projects (digitva-x79t). */
export async function getUserPlacement(request: JsonRequester, userId: string): Promise<OrgProject[]> {
  return ((await request(`${USERS_API}/${encodeURIComponent(userId)}/placement`)) as { projects: OrgProject[] }).projects;
}

export async function getSignInQrs(request: JsonRequester, userId: string): Promise<SignInQrItem[]> {
  return ((await request(`${USERS_API}/${encodeURIComponent(userId)}/sign-in-qr`)) as { items: SignInQrItem[] }).items;
}

/** delivery "show" returns the code once; "email" returns only the expiry. */
export async function issueSignInQr(request: JsonRequester, userId: string, delivery: "show" | "email"): Promise<SignInQrShown & { emailed?: boolean }> {
  return (await request(`${USERS_API}/${encodeURIComponent(userId)}/sign-in-qr`, { method: "POST", json: { delivery } })) as SignInQrShown & { emailed?: boolean };
}

export async function revokeSignInQr(request: JsonRequester, userId: string): Promise<boolean> {
  return ((await request(`${USERS_API}/${encodeURIComponent(userId)}/sign-in-qr`, { method: "DELETE" })) as { revoked: boolean }).revoked;
}

/** The sign-in QR is for accounts whose roles are only collector roles; the server decides (not_eligible), this just hides the obvious misses. */
export function signInQrCandidate(user: DirectoryUser): boolean {
  return user.active && user.grants.length > 0 && user.grants.every((g) => g.role === "interviewer" || g.role === "death_reporter");
}

export const PAGE_SIZE = 50;

/** The list URL for *filters* at *offset*: only the filters that are set, each encoded. */
export function usersQuery(filters: UserFilters, offset = 0, limit = PAGE_SIZE): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    const text = typeof value === "string" ? value.trim() : "";
    if (text && !(key === "status" && text === "all")) params.set(key, text);
  }
  params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  return `${USERS_API}?${params.toString()}`;
}

export async function getUsers(request: JsonRequester, filters: UserFilters, offset = 0): Promise<UsersPage> {
  return (await request(usersQuery(filters, offset))) as UsersPage;
}

export async function getUserActivity(request: JsonRequester, userId: string): Promise<UserActivity> {
  return (await request(`${USERS_API}/${encodeURIComponent(userId)}/activity`)) as UserActivity;
}

export async function issueEnrolmentCode(request: JsonRequester, userId: string, projectId: string): Promise<IssuedCode> {
  return (await request(`${USERS_API}/${encodeURIComponent(userId)}/enrolment-code`, {
    method: "POST",
    json: { project_id: projectId, delivery: "show" },
  })) as IssuedCode;
}

export async function emailEnrolmentCode(request: JsonRequester, userId: string, projectId: string): Promise<void> {
  await request(`${USERS_API}/${encodeURIComponent(userId)}/enrolment-code`, {
    method: "POST",
    json: { project_id: projectId, delivery: "email" },
  });
}

/** Device roles: the users the enrolment code is for (mobile-sign-in.md section 6). */
export const DEVICE_ROLES = ["interviewer", "death_reporter", "coder", "coding_tester", "reviewer"];

/** The projects where *user* holds a device role in the viewer's scope: the code's project choices. */
export function enrolmentProjects(user: DirectoryUser): { project_id: string; project_name: string }[] {
  const seen = new Map<string, string>();
  for (const grant of user.grants) {
    if (DEVICE_ROLES.includes(grant.role) && !seen.has(grant.project_id)) seen.set(grant.project_id, grant.project_name ?? grant.project_id);
  }
  return [...seen].map(([project_id, project_name]) => ({ project_id, project_name }));
}

/* ---------------------------------------------------------------------------
 * Admin tools (digitva-cgmc): account upload and the grant grid. The server refuses anyone but an admin
 * (docs/policy/access-control-model.md, "Users page admin tools").
 * ------------------------------------------------------------------------- */

/** The grid's six roles, in column order. */
export const GRID_ROLES = ["death_reporter", "interviewer", "interview_supervisor", "coder", "reviewer", "data_manager"] as const;
export type GridRole = (typeof GRID_ROLES)[number];

/** A directory grant plus its grid unit key: `project`, `site:<site_id>` or `unit:<org_unit_id>`. */
export interface GridGrant extends UserGrant {
  unit: string;
}

export interface GridUser {
  user_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  active: boolean;
  created_at: string | null;
  grants: GridGrant[];
  enrolment: UserEnrolment;
}

export interface GridOptions {
  mode: "organization" | "sites";
  units: { key: string; label: string; depth: number }[];
  cadres: { cadre_id: string; cadre_code: string; cadre_name: string }[];
}

export interface GridPage {
  users: GridUser[];
  total: number;
  limit: number;
  offset: number;
  options?: GridOptions;
}

export interface GridFilters {
  project: string;
  from?: string;
  to?: string;
  q?: string;
  role?: string;
  status?: "all" | "active" | "inactive";
}

export interface GridSave {
  project_id: string;
  unit: string;
  roles: GridRole[];
  cadre_id?: string;
  name?: string;
  phone?: string;
  active?: boolean;
}

export interface GridSaveResult {
  user: GridUser;
  changes: number;
  invited: boolean;
  enrolment_email: "sent" | "failed" | "no_email" | null;
  warnings: string[];
}

export const GRID_PAGE_SIZE = 50;

/** The grid URL for *filters* at *offset*: only the filters that are set, each encoded. */
export function gridQuery(filters: GridFilters, offset = 0, limit = GRID_PAGE_SIZE): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    const text = typeof value === "string" ? value.trim() : "";
    if (text && !(key === "status" && text === "all")) params.set(key, text);
  }
  params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  return `${USERS_API}/grid?${params.toString()}`;
}

export async function getGrid(request: JsonRequester, filters: GridFilters, offset = 0): Promise<GridPage> {
  return (await request(gridQuery(filters, offset))) as GridPage;
}

export async function saveGridRow(request: JsonRequester, userId: string, save: GridSave): Promise<GridSaveResult> {
  return (await request(`${USERS_API}/${encodeURIComponent(userId)}/grants`, { method: "POST", json: save })) as GridSaveResult;
}

/** The grid roles *user* holds at *unit*. */
export function rolesAt(user: GridUser, unit: string): GridRole[] {
  return GRID_ROLES.filter((role) => user.grants.some((g) => g.unit === unit && g.role === role));
}

/** The row's unit: where the user holds the most grid roles in the project, else the first offered unit. */
export function primaryUnit(user: GridUser, fallback: string): string {
  let best = fallback;
  let count = 0;
  for (const grant of user.grants) {
    const n = rolesAt(user, grant.unit).length;
    if (n > count) [best, count] = [grant.unit, n];
  }
  return best;
}

export type UploadStatus = "new" | "exists" | "invalid";

export interface UploadRow {
  row: number;
  name: string;
  email: string;
  phone: string | null;
  status: UploadStatus;
  reason: string | null;
  phone_clash: boolean;
}

export interface UploadResult {
  rows: UploadRow[];
  counts: Record<UploadStatus, number>;
  created?: number;
}

/** The upload body: the file's name and its bytes in base64. */
export interface UploadFile {
  filename: string;
  content: string;
}

export const UPLOAD_TEMPLATE = "name,email,phone\n";

export async function previewUpload(request: JsonRequester, file: UploadFile): Promise<UploadResult> {
  return (await request(`${USERS_API}/import/preview`, { method: "POST", json: file })) as UploadResult;
}

export async function applyUpload(request: JsonRequester, file: UploadFile): Promise<UploadResult> {
  return (await request(`${USERS_API}/import/apply`, { method: "POST", json: file })) as UploadResult;
}
