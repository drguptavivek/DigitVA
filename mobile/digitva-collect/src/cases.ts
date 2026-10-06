/**
 * Offline worklist cases (phase 3) in one interviewer's encrypted database:
 * the cases downloaded from /api/v1/intake/cases, deaths registered on the phone
 * and not yet sent, and contact attempts and visit dates queued for the
 * next sync. Everything here is in-flight work: downloaded cases are
 * replaced on every refresh (a case the server no longer lists is dropped,
 * so no history accumulates), and registrations and queued actions are
 * deleted once the server acknowledges them (push and purge).
 *
 * Names, phones and addresses live only in this encrypted store and are
 * never logged; logs carry client ids and error codes only.
 */
import type { SubmissionData, WhoVaHostPrefill } from "@drguptavivek/who-2022-va";

import { getDraftPrefill, getDraftRow, type Db, type DraftBinding, purgeProjectData } from "./drafts";
import type { StringKey } from "./i18n";

/** What the server's prefill builder returns (web_intake_service._prefill_from_death). */
export interface Prefill {
  interviewer?: WhoVaHostPrefill["interviewer"];
  deceased?: WhoVaHostPrefill["deceased"];
  answers?: SubmissionData;
  lockedQuestionNames?: string[];
}

/** One /api/v1/intake/cases row (serialize_worklist_row); phones are masked. */
export interface CaseRow {
  death_id: string;
  unique_id: string;
  project_id: string;
  site_id: string;
  org_unit_id: string | null;
  unit_name: string | null;
  state: string;
  source: string;
  details_pending: boolean;
  pending_flag: boolean;
  deceased_name: string | null;
  deceased_sex: string | null;
  age_years: number | null;
  date_of_death: string | null;
  registered_by_me: boolean;
  started_by_me: boolean;
  my_draft_id: string | null;
  other_draft_active?: boolean;
  other_draft_started_at?: string | null;
  other_complete_interview?: boolean;
  code_now?: boolean;
  va_sid: string | null;
  created_at: string;
  updated_at: string;
  next_visit_at: string | null;
  last_contact_at: string | null;
  informant_phone_masked: string | null;
  informant_phone_2_masked: string | null;
  possible_duplicates?: Array<{ death_id: string; unique_id: string }>;
}

export interface CaseDetail
  extends Omit<
    CaseRow,
    | "deceased_name"
    | "deceased_sex"
    | "age_years"
    | "date_of_death"
    | "informant_phone_masked"
    | "informant_phone_2_masked"
    | "possible_duplicates"
  > {
  deceased: {
    name: string | null;
    sex: string | null;
    age_years: number | null;
    date_of_birth: string | null;
    date_of_birth_partial: string | null;
    date_of_death: string | null;
    place_of_death: string | null;
  };
  household_address: {
    address: string | null;
    house_street: string | null;
    village_ward: string | null;
    landmark: string | null;
  };
  informant: { name: string | null; phone: string | null; phone_2: string | null };
  remarks: string | null;
  /** Present only when the caller may start or resume this interview. */
  prefill?: Prefill;
  links: { self: string; attempts: string; visit: string };
}

/** The web register form's fields, as typed (web_intake_service.register_death validates them again). */
export interface RegistrationFields {
  deceased_name: string;
  deceased_sex: string;
  date_of_death: string;
  date_of_birth?: string;
  date_of_birth_partial?: string;
  age_years?: string;
  abha_number?: string;
  abha_address?: string;
  place_of_death?: string;
  address?: string;
  address_house_street?: string;
  address_village_ward?: string;
  address_landmark?: string;
  informant_name?: string;
  informant_phone?: string;
  informant_phone_2?: string;
  father_name?: string;
  mother_name?: string;
  remarks?: string;
}

/** pending: waiting to send; needs_edit: the server refused it (or it can no longer apply) and the interviewer must edit or discard it. */
export type QueueState = "pending" | "needs_edit";

export interface Registration {
  client_death_id: string;
  project_id: string;
  site_id: string;
  org_unit_id: string | null;
  fields: RegistrationFields;
  state: QueueState;
  created_at: string;
}

export const CONTACT_OUTCOMES = ["reached", "no_answer", "wrong_number", "moved", "refused"] as const;
export type ContactOutcome = (typeof CONTACT_OUTCOMES)[number];

export interface CaseAction {
  client_id: string;
  project_id: string;
  kind: "attempt" | "visit";
  /** The server case; null while it hangs on an unsent registration. */
  death_id: string | null;
  client_death_id: string | null;
  body: { outcome?: ContactOutcome; next_visit_at?: string | null };
  state: QueueState;
  created_at: string;
}

// ---------------------------------------------------------------------------
// Downloaded cases
// ---------------------------------------------------------------------------

/**
 * Atomically make the stored cases exactly `rows`, in server order. Drafts
 * keep their own binding, so a dropped case never strands one.
 */
type CaseWriteDb = Pick<Db, "runAsync" | "getFirstAsync">;

type ExclusiveCaseDb = Db & {
  withExclusiveTransactionAsync?: (task: (transaction: CaseWriteDb) => Promise<void>) => Promise<void>;
};

export async function replaceCases(db: Db, projectId: string, rows: CaseDetail[]): Promise<void> {
  if (rows.some((row) => row.project_id !== projectId)) throw new Error("project_mismatch");
  const keep = rows.map((row) => row.death_id);
  const placeholders = keep.map(() => "?").join(", ");
  const replace = async (transaction: CaseWriteDb): Promise<void> => {
    for (const [position, row] of rows.entries()) {
      await upsertCaseInTransaction(transaction, row, position);
    }
    await transaction.runAsync(
      keep.length
        ? `DELETE FROM cases WHERE project_id = ? AND death_id NOT IN (${placeholders})`
        : "DELETE FROM cases WHERE project_id = ?",
      [projectId, ...keep]
    );
  };

  const nativeDb = db as ExclusiveCaseDb;
  if (nativeDb.withExclusiveTransactionAsync) {
    await nativeDb.withExclusiveTransactionAsync(replace);
    return;
  }

  await db.execAsync("BEGIN IMMEDIATE");
  try {
    await replace(db);
    await db.execAsync("COMMIT");
  } catch (error) {
    try {
      await db.execAsync("ROLLBACK");
    } catch {
      // Keep the write failure that caused the rollback.
    }
    throw error;
  }
}

export async function upsertCase(db: Db, row: CaseDetail, position = -1): Promise<void> {
  await upsertCaseInTransaction(db, row, position);
}

/** Upsert one case using only the executor methods supported by SQLite transactions. */
async function upsertCaseInTransaction(db: CaseWriteDb, row: CaseDetail, position: number): Promise<void> {
  const existing = await db.getFirstAsync<{ project_id: string | null }>(
    "SELECT project_id FROM cases WHERE death_id = ?",
    [row.death_id]
  );
  if (existing && existing.project_id !== row.project_id) throw new Error("project_mismatch");
  await db.runAsync(
    `INSERT INTO cases (death_id, project_id, position, row) VALUES (?, ?, ?, ?)
     ON CONFLICT(death_id) DO UPDATE SET project_id = excluded.project_id, position = excluded.position, row = excluded.row`,
    [row.death_id, row.project_id, position, JSON.stringify(row)]
  );
}

export async function listCases(db: Db): Promise<CaseDetail[]> {
  const rows = await db.getAllAsync<{ row: string }>("SELECT row FROM cases ORDER BY position, death_id", []);
  return rows.map((r) => JSON.parse(r.row) as CaseDetail);
}

export async function getCase(db: Db, deathId: string): Promise<CaseDetail | undefined> {
  const r = await db.getFirstAsync<{ row: string }>("SELECT row FROM cases WHERE death_id = ?", [deathId]);
  return r ? (JSON.parse(r.row) as CaseDetail) : undefined;
}

export const ACTIVE_CASE_STATES = [
  "registered",
  "scheduled",
  "in_progress",
  "paused",
  "not_reachable",
  "refused"
] as const;

export function isActiveCaseState(state: string): boolean {
  return (ACTIVE_CASE_STATES as readonly string[]).includes(state);
}

export function isCaseDetail(value: unknown): value is CaseDetail {
  if (!value || typeof value !== "object") return false;
  const detail = value as Partial<CaseDetail>;
  return (
    typeof detail.death_id === "string" && detail.death_id.length > 0 &&
    typeof detail.unique_id === "string" && detail.unique_id.length > 0 &&
    typeof detail.project_id === "string" && detail.project_id.length > 0 &&
    typeof detail.state === "string" &&
    typeof detail.site_id === "string" &&
    (!("code_now" in detail) || typeof detail.code_now === "boolean") &&
    (!("other_complete_interview" in detail) || typeof detail.other_complete_interview === "boolean") &&
    (detail.prefill === undefined || (typeof detail.prefill === "object" && detail.prefill !== null)) &&
    typeof detail.deceased === "object" &&
    detail.deceased !== null &&
    typeof detail.household_address === "object" &&
    detail.household_address !== null &&
    typeof detail.informant === "object" &&
    detail.informant !== null &&
    typeof detail.links === "object" &&
    detail.links !== null &&
    typeof detail.links.self === "string" &&
    typeof detail.links.attempts === "string" &&
    typeof detail.links.visit === "string"
  );
}

export async function deleteCase(db: Db, projectId: string, deathId: string): Promise<void> {
  await db.runAsync("DELETE FROM cases WHERE project_id = ? AND death_id = ?", [projectId, deathId]);
}

export { purgeProjectData };

// ---------------------------------------------------------------------------
// Offline registrations
// ---------------------------------------------------------------------------

type RegistrationRecord = Omit<Registration, "fields" | "project_id"> & { project_id: string | null; fields: string };

const toRegistration = (r: RegistrationRecord): Registration => {
  if (!r.project_id) throw new Error("project_id_required");
  return { ...r, project_id: r.project_id, fields: JSON.parse(r.fields) };
};

/** Save (or, after an edit, replace) a registration; it becomes pending again. */
export async function saveRegistration(
  db: Db,
  reg: {
    project_id: string;
    client_death_id: string;
    site_id: string;
    org_unit_id?: string | null;
    fields: RegistrationFields;
  }
): Promise<void> {
  const existing = await db.getFirstAsync<{ project_id: string | null }>(
    "SELECT project_id FROM registrations WHERE client_death_id = ?",
    [reg.client_death_id]
  );
  if (existing && existing.project_id !== reg.project_id) throw new Error("project_mismatch");
  await db.runAsync(
    `INSERT INTO registrations (client_death_id, project_id, site_id, org_unit_id, fields, state, created_at)
     VALUES (?, ?, ?, ?, ?, 'pending', ?)
     ON CONFLICT(client_death_id) DO UPDATE SET fields = excluded.fields, state = 'pending'`,
    [reg.client_death_id, reg.project_id, reg.site_id, reg.org_unit_id ?? null, JSON.stringify(reg.fields), new Date().toISOString()]
  );
}

export async function listRegistrations(db: Db): Promise<Registration[]> {
  const rows = await db.getAllAsync<RegistrationRecord>("SELECT * FROM registrations ORDER BY created_at", []);
  return rows.map(toRegistration);
}

export async function getRegistration(db: Db, clientDeathId: string): Promise<Registration | undefined> {
  const r = await db.getFirstAsync<RegistrationRecord>("SELECT * FROM registrations WHERE client_death_id = ?", [
    clientDeathId
  ]);
  return r ? toRegistration(r) : undefined;
}

export async function setRegistrationState(db: Db, clientDeathId: string, state: QueueState): Promise<void> {
  await db.runAsync("UPDATE registrations SET state = ? WHERE client_death_id = ?", [state, clientDeathId]);
}

/**
 * The server acknowledged a registration as `row`. Dependants are rebound
 * first, then the registration is deleted, then the case stored: if the app
 * dies in between, the registration is resent, answered 200 with the same
 * case, and the steps run again; never a draft left pointing at nothing.
 */
export async function acknowledgeRegistration(db: Db, clientDeathId: string, row: CaseDetail): Promise<void> {
  if (!isCaseDetail(row)) throw new Error("invalid_case_detail");
  const registration = await getRegistration(db, clientDeathId);
  if (!registration || registration.project_id !== row.project_id) throw new Error("project_mismatch");
  await db.runAsync("UPDATE drafts SET death_id = ?, unique_id = ? WHERE project_id = ? AND client_death_id = ?", [
    row.death_id,
    row.unique_id,
    row.project_id,
    clientDeathId
  ]);
  await db.runAsync("UPDATE case_actions SET death_id = ? WHERE project_id = ? AND client_death_id = ?", [
    row.death_id,
    row.project_id,
    clientDeathId
  ]);
  await db.runAsync("DELETE FROM registrations WHERE client_death_id = ?", [clientDeathId]);
  if (isActiveCaseState(row.state)) await upsertCase(db, row);
  else await deleteCase(db, row.project_id, row.death_id);
}

/** Discard a registration and everything queued on it that was never sent (drafts are kept, unbound: the interviewer decides). */
export async function discardRegistration(db: Db, clientDeathId: string): Promise<void> {
  await db.runAsync("DELETE FROM case_actions WHERE client_death_id = ? AND death_id IS NULL", [clientDeathId]);
  await db.runAsync("DELETE FROM registrations WHERE client_death_id = ?", [clientDeathId]);
}

// ---------------------------------------------------------------------------
// Queued attempts and visits
// ---------------------------------------------------------------------------

type ActionRecord = Omit<CaseAction, "body"> & { body: string };

const toAction = (r: ActionRecord): CaseAction => ({ ...r, body: JSON.parse(r.body) });

/** Queue (or, after an edit, replace) an attempt or visit; it becomes pending again. */
export async function queueAction(
  db: Db,
  action: Pick<CaseAction, "project_id" | "client_id" | "kind" | "body"> & {
    death_id?: string | null;
    client_death_id?: string | null;
  }
): Promise<void> {
  const existing = await db.getFirstAsync<{ project_id: string | null }>(
    "SELECT project_id FROM case_actions WHERE client_id = ?",
    [action.client_id]
  );
  if (existing && existing.project_id !== action.project_id) throw new Error("project_mismatch");
  await db.runAsync(
    `INSERT INTO case_actions (client_id, project_id, kind, death_id, client_death_id, body, state, created_at)
     VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
     ON CONFLICT(client_id) DO UPDATE SET body = excluded.body, state = 'pending'`,
    [
      action.client_id,
      action.project_id,
      action.kind,
      action.death_id ?? null,
      action.client_death_id ?? null,
      JSON.stringify(action.body),
      new Date().toISOString()
    ]
  );
}

/** Every queued action, oldest first (the order they are sent in). */
export async function listActions(db: Db): Promise<CaseAction[]> {
  const rows = await db.getAllAsync<ActionRecord>("SELECT * FROM case_actions ORDER BY created_at, client_id", []);
  return rows.map(toAction);
}

export async function setActionState(db: Db, clientId: string, state: QueueState): Promise<void> {
  await db.runAsync("UPDATE case_actions SET state = ? WHERE client_id = ?", [state, clientId]);
}

export async function deleteAction(db: Db, clientId: string): Promise<void> {
  await db.runAsync("DELETE FROM case_actions WHERE client_id = ?", [clientId]);
}

// ---------------------------------------------------------------------------
// Registration form rules and prefill
// ---------------------------------------------------------------------------

export const SEX_VALUES = ["male", "female", "undetermined", "unknown"] as const;
export const MAX_REGISTRATION_AGE = 125;
export const AGE_REVIEW_THRESHOLD = 85;
const PHONE = /^(?:\+91|0)?([6-9]\d{9})$/;
const ABHA_NUMBER = /^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$/;
const ABHA_ADDRESS = /^[A-Za-z0-9._]{4,32}@(abdm|sbx)$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const PARTIAL_BIRTH_DATE = /^(?:\d{4}|\d{4}-(0[1-9]|1[0-2]))$/;

/** An Indian mobile number as the server stores it (10 digits), or null when it is not one. Mirrors web_intake_service._clean_phone. */
export function normalisePhone(value: string): string | null {
  return PHONE.exec(value.replace(/[\s-]/g, ""))?.[1] ?? null;
}

function isRealDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function isPartialBirthDate(value: string): boolean {
  if (!PARTIAL_BIRTH_DATE.test(value)) return false;
  if (value.length === 4) return true;
  const month = Number(value.slice(5, 7));
  return month >= 1 && month <= 12;
}

export interface RegistrationAgeRange {
  /** The age if the person was born on the latest possible date. */
  youngestPossibleAge: number;
  /** The age if the person was born on the earliest possible date. */
  oldestPossibleAge: number;
}

function dateParts(value: string): [number, number, number] | undefined {
  if (!isRealDate(value)) return undefined;
  return [Number(value.slice(0, 4)), Number(value.slice(5, 7)), Number(value.slice(8, 10))];
}

function ageAtDeath(birth: [number, number, number], death: [number, number, number]): number {
  let age = death[0] - birth[0];
  if (death[1] < birth[1] || (death[1] === birth[1] && death[2] < birth[2])) age -= 1;
  return age;
}

function birthBounds(value: string): [[number, number, number], [number, number, number]] | undefined {
  if (/^\d{4}$/.test(value)) {
    const year = Number(value);
    return [[year, 1, 1], [year, 12, 31]];
  }
  if (/^\d{4}-\d{2}$/.test(value)) {
    const year = Number(value.slice(0, 4));
    const month = Number(value.slice(5, 7));
    const lastDay = new Date(Date.UTC(year, month, 0)).getUTCDate();
    return [[year, month, 1], [year, month, lastDay]];
  }
  const exact = dateParts(value);
  return exact ? [exact, exact] : undefined;
}

/** Return the complete age range implied by an exact or partial birth date. */
export function registrationAgeRange(fields: Pick<RegistrationFields, "date_of_death" | "date_of_birth" | "date_of_birth_partial">): RegistrationAgeRange | undefined {
  const death = dateParts(fields.date_of_death?.trim() ?? "");
  if (!death) return undefined;
  const birthValue = fields.date_of_birth?.trim() || fields.date_of_birth_partial?.trim();
  if (!birthValue) return undefined;
  const bounds = birthBounds(birthValue);
  if (!bounds) return undefined;
  return {
    youngestPossibleAge: ageAtDeath(bounds[1], death),
    oldestPossibleAge: ageAtDeath(bounds[0], death)
  };
}

/** Whether a valid registration needs an explicit confirmation for age over 85. */
export function registrationNeedsAgeConfirmation(fields: RegistrationFields): boolean {
  const age = fields.age_years?.trim() ?? "";
  if (/^\d{1,3}$/.test(age) && Number(age) > AGE_REVIEW_THRESHOLD) return true;
  return (registrationAgeRange(fields)?.oldestPossibleAge ?? 0) > AGE_REVIEW_THRESHOLD;
}

/**
 * The register form's rules (web_intake_service.register_death), checked
 * before a registration is queued so most refusals never need a round trip.
 * `today` is YYYY-MM-DD in the phone's time zone. Returns the problem per
 * field as a UI string key; empty when the form may be saved.
 */
export function validateRegistration(
  fields: RegistrationFields,
  today: string
): Partial<Record<keyof RegistrationFields, StringKey>> {
  const errors: Partial<Record<keyof RegistrationFields, StringKey>> = {};
  const value = (key: keyof RegistrationFields) => (fields[key] ?? "").trim();
  if (!value("deceased_name")) errors.deceased_name = "errRequired";
  if (!(SEX_VALUES as readonly string[]).includes(value("deceased_sex"))) errors.deceased_sex = "errRequired";
  for (const key of ["date_of_death", "date_of_birth"] as const) {
    const v = value(key);
    if (!v) continue;
    if (!isRealDate(v)) errors[key] = "errDate";
    else if (v > today) errors[key] = "errFutureDate";
  }
  const partialBirth = value("date_of_birth_partial");
  if (partialBirth && !isPartialBirthDate(partialBirth)) errors.date_of_birth_partial = "errDate";
  if (value("date_of_birth") && partialBirth) errors.date_of_birth_partial = "errBirthPrecision";
  if (!value("date_of_death")) errors.date_of_death = "errRequired";
  if (!errors.date_of_birth && !errors.date_of_death && value("date_of_birth") && value("date_of_birth") > value("date_of_death")) {
    errors.date_of_birth = "errBirthAfterDeath";
  }
  if (!errors.date_of_birth_partial && !errors.date_of_death && partialBirth) {
    const death = value("date_of_death");
    const partialComparable = partialBirth.length === 4 ? partialBirth : partialBirth;
    const deathComparable = partialBirth.length === 4 ? death.slice(0, 4) : death.slice(0, 7);
    if (partialBirth > today.slice(0, partialBirth.length)) errors.date_of_birth_partial = "errFutureDate";
    else if (partialComparable > deathComparable) errors.date_of_birth_partial = "errBirthAfterDeath";
  }
  const age = value("age_years");
  if (age && !(/^\d{1,3}$/.test(age) && Number(age) <= MAX_REGISTRATION_AGE)) errors.age_years = "errAge";
  if (!errors.date_of_birth && !errors.date_of_birth_partial && !errors.date_of_death) {
    const range = registrationAgeRange(fields);
    if (range && range.youngestPossibleAge > MAX_REGISTRATION_AGE) {
      if (value("date_of_birth")) errors.date_of_birth = "errAge";
      else if (partialBirth) errors.date_of_birth_partial = "errAge";
    }
  }
  if (value("abha_number") && !ABHA_NUMBER.test(value("abha_number"))) errors.abha_number = "errAbhaNumber";
  if (value("abha_address") && !ABHA_ADDRESS.test(value("abha_address"))) errors.abha_address = "errAbhaAddress";
  for (const key of ["informant_phone", "informant_phone_2"] as const) {
    if (value(key) && !normalisePhone(value(key))) errors[key] = "errPhone";
  }
  return errors;
}

/** Trimmed fields with blanks dropped: what is stored and sent. */
export function cleanRegistration(fields: RegistrationFields): RegistrationFields {
  const clean: Record<string, string> = {};
  for (const [key, raw] of Object.entries(fields)) {
    const v = typeof raw === "string" ? raw.trim() : "";
    if (v) clean[key] = v;
  }
  return clean as unknown as RegistrationFields;
}

/**
 * The prefill for an interview on a registration the server has not seen
 * yet: the deceased's identity and the informant's and parents' names,
 * following the server's rules (first word the given name, the rest the
 * surname; age prefilled for adults only). Area presets and organization
 * path names need the server. A cached interviewer identity may be supplied
 * by the caller without a network request.
 */
export function prefillFromRegistration(
  fields: RegistrationFields,
  interviewer?: Pick<NonNullable<WhoVaHostPrefill["interviewer"]>, "name" | "id">
): Prefill {
  const [givenNames, ...rest] = fields.deceased_name.trim().split(/\s+/);
  const sex = fields.deceased_sex === "male" || fields.deceased_sex === "female" ? fields.deceased_sex : "undetermined";
  const deceased: Record<string, unknown> = { givenNames, sex, dateOfDeath: fields.date_of_death };
  if (rest.length) deceased.surname = rest.join(" ");
  const age = fields.age_years ? Number(fields.age_years) : undefined;
  if (fields.date_of_birth) deceased.dateOfBirth = fields.date_of_birth;
  const answers: SubmissionData = {};
  const lockedQuestionNames: string[] = [];
  if (!fields.date_of_birth && typeof age === "number" && Number.isInteger(age)) {
    if (age >= 12 && age <= 119) {
      deceased.ageInYears = age;
      answers.age_group = "adult";
      answers.age_adult = age;
    } else if (age >= 1 && age <= 11) {
      answers.Id10020 = "no";
      answers.age_group = "child";
      answers.age_child_unit = "years";
      answers.age_child_years = age;
    }
  }
  if (!fields.date_of_birth && fields.date_of_birth_partial) {
    const partial = fields.date_of_birth_partial.trim();
    answers.Id10020 = "no";
    if (/^\d{4}-\d{2}$/.test(partial)) {
      answers.dob_precision = "month_year";
      answers.dob_month_year = `${partial}-01`;
    } else if (/^\d{4}$/.test(partial)) {
      answers.dob_precision = "year";
      answers.dob_year = `${partial}-01-01`;
    }
  }
  // Keep this in the same order as web_intake_service._case_address. The
  // offline registration has no organization path, so the available address
  // is both the usual residence (Id10055) and death location (Id10057).
  const address = [fields.address_house_street, fields.address_village_ward, fields.address_landmark, fields.address]
    .map((part) => part?.trim())
    .filter((part): part is string => Boolean(part))
    .join(", ");
  if (address) {
    answers.Id10051 = "yes";
    answers.Id10055 = address;
    answers.Id10057 = address;
  }
  if (fields.informant_name?.trim()) answers.Id10007 = fields.informant_name.trim();
  if (fields.father_name?.trim()) answers.Id10061 = fields.father_name.trim();
  if (fields.mother_name?.trim()) answers.Id10062 = fields.mother_name.trim();
  const cachedInterviewer = interviewer && (interviewer.name?.trim() || interviewer.id?.trim())
    ? {
        ...(interviewer.name?.trim() ? { name: interviewer.name.trim() } : {}),
        ...(interviewer.id?.trim() ? { id: interviewer.id.trim() } : {})
      }
    : undefined;
  lockedQuestionNames.push(
    ...(cachedInterviewer?.name ? ["Id10010"] : []),
    ...(cachedInterviewer?.id ? ["Id10010c"] : [])
  );
  return {
    ...(cachedInterviewer ? { interviewer: cachedInterviewer } : {}),
    deceased: deceased as Prefill["deceased"],
    answers,
    lockedQuestionNames
  };
}

/** A visit date picked as YYYY-MM-DD, as the date-time with a time zone the server wants: 09:00 on the phone's clock. */
export function visitAt(date: string): string | null {
  if (!isRealDate(date)) return null;
  const at = new Date(`${date}T09:00:00`);
  return Number.isNaN(at.getTime()) ? null : at.toISOString();
}

/** Today as YYYY-MM-DD on the phone's clock. */
export function localToday(now = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** Where a draft's site, unit, case binding and prefill come from. */
export interface DraftHost {
  projectId: string;
  siteId: string;
  orgUnitId?: string;
  binding: DraftBinding;
  prefill?: Prefill;
}

/**
 * Resolve the form's host for `draftId`: the stored draft itself (its own
 * binding and prefill, so a case pruned meanwhile changes nothing), else the
 * downloaded case (`deathId`) or offline registration (`clientDeathId`) it
 * is being started on, else a direct start at `siteId`. "completed" for a
 * draft already finished; undefined when nothing resolves.
 */
export async function resolveDraftHost(
  db: Db,
  draftId: string,
  params: { projectId: string; siteId?: string; orgUnitId?: string; deathId?: string; clientDeathId?: string }
): Promise<DraftHost | "completed" | undefined> {
  const row = await getDraftRow(db, draftId);
  if (row?.completed) return "completed";
  if (row) {
    if (!row.project_id) throw new Error("project_id_required");
    if (row.project_id !== params.projectId) throw new Error("project_mismatch");
    const prefill = await getDraftPrefill<Prefill>(db, draftId);
    return {
      projectId: row.project_id,
      siteId: row.site_id,
      orgUnitId: row.org_unit_id ?? undefined,
      binding: {
        projectId: row.project_id,
        ...(row.death_id ? { deathId: row.death_id } : {}),
        ...(row.unique_id ? { uniqueId: row.unique_id } : {}),
        ...(row.client_death_id ? { clientDeathId: row.client_death_id } : {})
      },
      prefill
    };
  }
  if (params.deathId) {
    const found = await getCase(db, params.deathId);
    if (!found || found.project_id !== params.projectId) return undefined;
    return {
      projectId: found.project_id,
      siteId: found.site_id,
      orgUnitId: found.org_unit_id ?? undefined,
      binding: { projectId: found.project_id, deathId: found.death_id, uniqueId: found.unique_id, prefill: found.prefill },
      prefill: found.prefill
    };
  }
  if (params.clientDeathId) {
    const reg = await getRegistration(db, params.clientDeathId);
    if (!reg || reg.project_id !== params.projectId) return undefined;
    const prefill = prefillFromRegistration(reg.fields);
    return {
      projectId: reg.project_id,
      siteId: reg.site_id,
      orgUnitId: reg.org_unit_id ?? undefined,
      binding: { projectId: reg.project_id, clientDeathId: reg.client_death_id, prefill },
      prefill
    };
  }
  return params.siteId
    ? { projectId: params.projectId, siteId: params.siteId, orgUnitId: params.orgUnitId, binding: { projectId: params.projectId } }
    : undefined;
}
