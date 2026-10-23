/**
 * What the server checks before it takes an interview, run on the phone before the interview is marked ready
 * to send (docs/policy/expo-client.md, "Refused uploads on the phone"). Mirrors web_intake_service
 * `_identity_from_answers`, `_approximate_date_of_death` and `_interview_outcome`, with the same messages
 * (the en.json entries repeat the server's text). A failing interview stays a draft with the reason shown.
 */
import type { SubmissionData } from "@drguptavivek/who-2022-va";
import type { StringKey } from "./i18n";
import { correctedNow } from "./phoneClock";

export interface PreSendIssue {
  message: StringKey;
  /** WHO question names to fix, as the server's `fields`. */
  fields: string[];
}

const SEX_VALUES = ["male", "female", "undetermined", "unknown"];

const text = (value: unknown) => (value == null ? "" : String(value).trim());

/** An ISO date (YYYY-MM-DD prefix) that exists and is not after `today`. */
function validPastDate(raw: unknown, today: Date): boolean {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(text(raw));
  if (!match) return false;
  const [year, month, day] = [Number(match[1]), Number(match[2]), Number(match[3])];
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return false;
  return date.getTime() <= Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
}

/** Whether the answers give the date of death: the exact date, or (date not known) a year 1900..this year. */
function hasDateOfDeath(data: SubmissionData, today: Date): boolean {
  const known = text(data.Id10022) === "yes";
  const exact = text(data.Id10023) || (known ? text(text(data.Id10020) === "yes" ? data.Id10023_a : data.Id10023_b) : "");
  if (validPastDate(exact, today)) return true;
  if (known) return false;
  const year = text(data.Id10024).slice(0, 4);
  return /^\d{4}$/.test(year) && Number(year) >= 1900 && Number(year) <= today.getFullYear();
}

/** A date that exists, not in the future (the server's `_clean_date`). */
const pastDate = (raw: unknown, today: Date) => validPastDate(raw, today) && text(raw).length === 10;

/**
 * Every issue that would make the server refuse this interview, in the server's order (`_interview_outcome`,
 * then identity or, for a refusal with no identity, the visit note). `direct`: the interview is not bound to a
 * registered case (a direct start takes its identity from the answers); a registered case already has one.
 * `valid`: the form engine's verdict.
 */
export function preSendIssues(data: SubmissionData, opts: { valid: boolean; direct: boolean; today?: Date }): PreSendIssue[] {
  const today = opts.today ?? correctedNow();
  const consent = text(data.Id10013).toLowerCase();
  const issues: PreSendIssue[] = [];
  if (consent === "no") {
    // A refusal needs no identity, but a direct start has none: it carries a visit note instead.
    if (opts.direct) {
      const fields = [
        ...(text(data.visit_address) ? [] : ["visit_address"]),
        ...(pastDate(data.visit_date, today) ? [] : ["visit_date"]),
      ];
      if (fields.length) issues.push({ message: "preVisitNoteMissing", fields });
    }
    return issues;
  }
  if (consent === "yes" && text(data.interview_outcome) === "refused") {
    issues.push({ message: "preOutcomeConflictsConsent", fields: ["Id10013", "interview_outcome"] });
  }
  if (opts.valid && !consent) issues.push({ message: "preConsentUnanswered", fields: ["Id10013"] });
  if (opts.direct) {
    const fields: string[] = [];
    if (!text(data.Id10017) && !text(data.Id10018)) fields.push("Id10017", "Id10018");
    if (!SEX_VALUES.includes(text(data.Id10019))) fields.push("Id10019");
    if (!hasDateOfDeath(data, today)) fields.push("Id10022", ...(text(data.Id10022) === "yes" ? ["Id10023_a", "Id10023_b"] : ["Id10024"]));
    if (fields.length) issues.push({ message: "preIdentityMissing", fields });
  }
  return issues;
}
