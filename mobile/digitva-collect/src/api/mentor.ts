/** Institute staff and mentor-view endpoints; calls go through ../api's shared transport. */
import { requestJson } from "../api";
import type { ClientCsrf } from "./types";

export interface MentoringDistrict {
  project_id: string;
  project_name: string;
  org_unit_id: string;
  unit_code: string;
  unit_name: string;
}

export interface MentoringInstituteSummary {
  institute_code: string;
  institute_name: string;
  is_active: boolean;
  is_admin: boolean;
  districts: MentoringDistrict[];
}

export interface MentoringLanguage {
  language_code: string;
  language_name: string;
}

export interface MentoringSummary {
  is_member: boolean;
  is_institute_admin: boolean;
  institutes: MentoringInstituteSummary[];
  languages: MentoringLanguage[];
}

export interface MentorStaffMember {
  user_id: string;
  email: string | null;
  name: string;
  job_title: string | null;
  is_admin: boolean;
  account_status: string;
}

export interface CreateMentorStaffPayload {
  name: string;
  email: string;
  email_confirm: string;
  job_title?: string;
  phone?: string;
  languages: string[];
}

export async function getMentoringSummary(
  csrf?: ClientCsrf,
  server = "",
  token?: string,
): Promise<MentoringSummary> {
  const response = await requestJson<MentoringSummary>(server, "/api/v1/me/mentoring", {
    csrf,
    token,
  });
  return response.body;
}

export async function listMentorInstituteStaff(
  instituteCode: string,
  csrf?: ClientCsrf,
  server = "",
): Promise<{ staff: MentorStaffMember[] }> {
  const response = await requestJson<{ staff: MentorStaffMember[] }>(
    server,
    `/admin/api/mentor-institutes/${encodeURIComponent(instituteCode)}/staff`,
    { csrf },
  );
  return response.body;
}

export async function createMentorInstituteStaff(
  instituteCode: string,
  payload: CreateMentorStaffPayload,
  csrf?: ClientCsrf,
  server = "",
): Promise<{ staff: MentorStaffMember; sign_in_code?: string }> {
  const response = await requestJson<{ staff: MentorStaffMember; sign_in_code?: string }>(
    server,
    `/admin/api/mentor-institutes/${encodeURIComponent(instituteCode)}/staff`,
    {
      method: "POST",
      json: payload,
      csrf,
    },
  );
  return response.body;
}

export async function removeMentorInstituteStaff(
  instituteCode: string,
  userId: string,
  csrf?: ClientCsrf,
  server = "",
): Promise<{ user_id: string; account_deactivated: boolean; grants_deactivated: number }> {
  const response = await requestJson<{
    user_id: string;
    account_deactivated: boolean;
    grants_deactivated: number;
  }>(
    server,
    `/admin/api/mentor-institutes/${encodeURIComponent(instituteCode)}/staff/${encodeURIComponent(userId)}/remove`,
    {
      method: "POST",
      csrf,
    },
  );
  return response.body;
}

// Mentor view (/api/v1/mentor, docs/policy/mentor-view.md). Cookie session only; the server decides every scope.

export type MentorPeriod = "30d" | "90d" | "12m" | "all";

export interface MentorDistrict {
  district_id: string;
  code: string;
  name: string;
  project_id: string;
  project_name: string;
}

export interface MentorCoderRow {
  label: string;
  coder_id?: string;
  ready: number;
  coded: number;
  reviewed_agreed: number;
  reviewed_changed: number;
  not_codeable: number;
  recodes: number;
  last_active: string | null;
}

export interface MentorNote {
  note_id: string;
  va_sid: string;
  body: string;
  created_at: string;
  read: boolean;
  author_name: string;
  author_basis: string;
  institute_name: string | null;
  mine: boolean;
  can_retract: boolean;
}

export interface MentorCase {
  va_sid: string;
  coded_at: string;
  final_cod: string;
  review_outcome: "not_reviewed" | "agreed" | "changed";
  notes: MentorNote[];
}

export async function getMentorDistricts(csrf?: ClientCsrf): Promise<{ districts: MentorDistrict[] }> {
  return (await requestJson<{ districts: MentorDistrict[] }>("", "/api/v1/mentor/districts", { csrf })).body;
}

export async function getMentorCoders(
  district: string,
  period: MentorPeriod,
  csrf?: ClientCsrf,
): Promise<{ names_visible: boolean; coders: MentorCoderRow[]; truncated: boolean }> {
  const query = `district=${encodeURIComponent(district)}&period=${period}`;
  return (await requestJson<{ names_visible: boolean; coders: MentorCoderRow[]; truncated: boolean }>(
    "", `/api/v1/mentor/coders?${query}`, { csrf },
  )).body;
}

export async function getMentorCoderCases(
  district: string,
  coderId: string,
  period: MentorPeriod,
  after: string | null,
  csrf?: ClientCsrf,
): Promise<{ cases: MentorCase[]; next: string | null }> {
  let query = `district=${encodeURIComponent(district)}&period=${period}`;
  if (after) query += `&after=${encodeURIComponent(after)}`;
  return (await requestJson<{ cases: MentorCase[]; next: string | null }>(
    "", `/api/v1/mentor/coders/${encodeURIComponent(coderId)}/cases?${query}`, { csrf },
  )).body;
}

export async function createMentorNote(vaSid: string, body: string, csrf?: ClientCsrf): Promise<MentorNote> {
  return (await requestJson<MentorNote>("", `/api/v1/mentor/cases/${encodeURIComponent(vaSid)}/notes`, {
    method: "POST", json: { body }, csrf,
  })).body;
}

export async function retractMentorNote(noteId: string, csrf?: ClientCsrf): Promise<void> {
  await requestJson("", `/api/v1/mentor/notes/${encodeURIComponent(noteId)}/retract`, { method: "POST", csrf });
}

export async function getMyMentorFeedback(
  csrf?: ClientCsrf,
): Promise<{ notes: MentorNote[]; unread_count: number; next: string | null }> {
  return (await requestJson<{ notes: MentorNote[]; unread_count: number; next: string | null }>(
    "", "/api/v1/mentor/feedback/mine", { csrf },
  )).body;
}

export async function markMentorFeedbackRead(noteId: string, csrf?: ClientCsrf): Promise<void> {
  await requestJson("", `/api/v1/mentor/feedback/${encodeURIComponent(noteId)}/read`, { method: "POST", csrf });
}
