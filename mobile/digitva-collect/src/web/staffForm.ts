/**
 * The Add Staff form's rules (Mentoring > Institute roster). Pure: takes what was typed, returns the first
 * message to show or the payload to send. `languageCount` is how many coding languages the institute offers;
 * a choice is required only when there are some. The messages are English only, as the form's other text is.
 */
import type { CreateMentorStaffPayload } from "../api";

export interface StaffFormInput {
  name: string;
  email: string;
  emailConfirm: string;
  jobTitle: string;
  phone: string;
  selectedLanguages: string[];
}

export type StaffFormResult =
  | { error: string }
  | { error?: undefined; email: string; payload: CreateMentorStaffPayload };

export function validateStaffForm(input: StaffFormInput, languageCount: number): StaffFormResult {
  const trimmedName = input.name.trim();
  const trimmedEmail = input.email.trim().toLowerCase();
  const trimmedConfirm = input.emailConfirm.trim().toLowerCase();
  const trimmedJob = input.jobTitle.trim();
  const cleanedPhone = input.phone.trim().replace(/[\s-]/g, "");

  if (!trimmedName) return { error: "Full Name is required." };
  if (!trimmedEmail) return { error: "Email is required." };
  if (!trimmedConfirm) return { error: "Confirm Email is required." };
  if (trimmedEmail !== trimmedConfirm) return { error: "Email confirmation does not match." };
  if (languageCount > 0 && input.selectedLanguages.length === 0) {
    return { error: "At least one coding language must be selected." };
  }
  if (cleanedPhone && !/^\d{10}$/.test(cleanedPhone)) return { error: "Enter a valid 10-digit mobile number." };

  const payload: CreateMentorStaffPayload = {
    name: trimmedName,
    email: trimmedEmail,
    email_confirm: trimmedConfirm,
    languages: input.selectedLanguages,
  };
  if (trimmedJob) payload.job_title = trimmedJob;
  if (cleanedPhone) payload.phone = cleanedPhone;
  return { email: trimmedEmail, payload };
}
