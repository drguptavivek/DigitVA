/** The Users page calls (digitva-75wn) over the browser session, through the shared JSON requester. The server scopes every reply (docs/policy/access-control-model.md, "Users page"). */
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
