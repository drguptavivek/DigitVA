/**
 * Offline worklist cases (phase 3) in one interviewer's encrypted database:
 * the cases downloaded from /device/cases, deaths registered on the phone
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

import { getDraftPrefill, getDraftRow, type Db, type DraftBinding } from "./drafts";
import type { StringKey } from "./i18n";

/** What the server's prefill builder returns (web_intake_service._prefill_from_death). */
export interface Prefill {
  interviewer?: WhoVaHostPrefill["interviewer"];
  deceased?: WhoVaHostPrefill["deceased"];
  answers?: SubmissionData;
  lockedQuestionNames?: string[];
}

/** One /device/cases row (serialize_worklist_row plus prefill); phones masked. */
export interface CaseRow {
  death_id: string;
  unique_id: string;
  site_id: string;
  org_unit_id: string | null;
  unit_name: string | null;
  state: string;
  deceased_name: string | null;
  deceased_sex: string | null;
  age_years: number | null;
  date_of_death: string | null;
  next_visit_at: string | null;
  last_contact_at: string | null;
  informant_phone_masked: string | null;
  informant_phone_2_masked: string | null;
  prefill: Prefill;
}

/** The web register form's fields, as typed (web_intake_service.register_death validates them again). */
export interface RegistrationFields {
  deceased_name: string;
  deceased_sex: string;
  date_of_death: string;
  date_of_birth?: string;
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
 * Make the stored cases exactly `rows`, in server order: upsert each, then
 * drop every case not listed (pruning). Drafts keep their own binding, so a
 * dropped case never strands one.
 */
export async function replaceCases(db: Db, rows: CaseRow[]): Promise<void> {
  for (const [position, row] of rows.entries()) await upsertCase(db, row, position);
  const keep = rows.map((row) => row.death_id);
  const placeholders = keep.map(() => "?").join(", ");
  await db.runAsync(
    keep.length ? `DELETE FROM cases WHERE death_id NOT IN (${placeholders})` : "DELETE FROM cases",
    keep
  );
}

export async function upsertCase(db: Db, row: CaseRow, position = -1): Promise<void> {
  await db.runAsync(
    `INSERT INTO cases (death_id, position, row) VALUES (?, ?, ?)
     ON CONFLICT(death_id) DO UPDATE SET position = excluded.position, row = excluded.row`,
    [row.death_id, position, JSON.stringify(row)]
  );
}

export async function listCases(db: Db): Promise<CaseRow[]> {
  const rows = await db.getAllAsync<{ row: string }>("SELECT row FROM cases ORDER BY position, death_id", []);
  return rows.map((r) => JSON.parse(r.row) as CaseRow);
}

export async function getCase(db: Db, deathId: string): Promise<CaseRow | undefined> {
  const r = await db.getFirstAsync<{ row: string }>("SELECT row FROM cases WHERE death_id = ?", [deathId]);
  return r ? (JSON.parse(r.row) as CaseRow) : undefined;
}

// ---------------------------------------------------------------------------
// Offline registrations
// ---------------------------------------------------------------------------

type RegistrationRecord = Omit<Registration, "fields"> & { fields: string };

const toRegistration = (r: RegistrationRecord): Registration => ({ ...r, fields: JSON.parse(r.fields) });

/** Save (or, after an edit, replace) a registration; it becomes pending again. */
export async function saveRegistration(
  db: Db,
  reg: { client_death_id: string; site_id: string; org_unit_id?: string | null; fields: RegistrationFields }
): Promise<void> {
  await db.runAsync(
    `INSERT INTO registrations (client_death_id, site_id, org_unit_id, fields, state, created_at)
     VALUES (?, ?, ?, ?, 'pending', ?)
     ON CONFLICT(client_death_id) DO UPDATE SET fields = excluded.fields, state = 'pending'`,
    [reg.client_death_id, reg.site_id, reg.org_unit_id ?? null, JSON.stringify(reg.fields), new Date().toISOString()]
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
export async function acknowledgeRegistration(db: Db, clientDeathId: string, row: CaseRow): Promise<void> {
  await db.runAsync("UPDATE drafts SET death_id = ?, unique_id = ? WHERE client_death_id = ?", [
    row.death_id,
    row.unique_id,
    clientDeathId
  ]);
  await db.runAsync("UPDATE case_actions SET death_id = ? WHERE client_death_id = ?", [row.death_id, clientDeathId]);
  await db.runAsync("DELETE FROM registrations WHERE client_death_id = ?", [clientDeathId]);
  await upsertCase(db, row);
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
  action: Pick<CaseAction, "client_id" | "kind" | "body"> & { death_id?: string | null; client_death_id?: string | null }
): Promise<void> {
  await db.runAsync(
    `INSERT INTO case_actions (client_id, kind, death_id, client_death_id, body, state, created_at)
     VALUES (?, ?, ?, ?, ?, 'pending', ?)
     ON CONFLICT(client_id) DO UPDATE SET body = excluded.body, state = 'pending'`,
    [
      action.client_id,
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
const PHONE = /^(?:\+91|0)?([6-9]\d{9})$/;
const ABHA_NUMBER = /^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$/;
const ABHA_ADDRESS = /^[A-Za-z0-9._]{4,32}@(abdm|sbx)$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

/** An Indian mobile number as the server stores it (10 digits), or null when it is not one. Mirrors web_intake_service._clean_phone. */
export function normalisePhone(value: string): string | null {
  return PHONE.exec(value.replace(/[\s-]/g, ""))?.[1] ?? null;
}

function isRealDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
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
  if (!value("date_of_death")) errors.date_of_death = "errRequired";
  if (!errors.date_of_birth && !errors.date_of_death && value("date_of_birth") && value("date_of_birth") > value("date_of_death")) {
    errors.date_of_birth = "errBirthAfterDeath";
  }
  const age = value("age_years");
  if (age && !(/^\d{1,3}$/.test(age) && Number(age) <= 130)) errors.age_years = "errAge";
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
 * surname; age prefilled for adults only). Area presets, the address and
 * the interviewer's locked identity need the server and are not prefilled.
 */
export function prefillFromRegistration(fields: RegistrationFields): Prefill {
  const [givenNames, ...rest] = fields.deceased_name.trim().split(/\s+/);
  const sex = fields.deceased_sex === "male" || fields.deceased_sex === "female" ? fields.deceased_sex : "undetermined";
  const deceased: Record<string, unknown> = { givenNames, sex, dateOfDeath: fields.date_of_death };
  if (rest.length) deceased.surname = rest.join(" ");
  const age = fields.age_years ? Number(fields.age_years) : undefined;
  if (fields.date_of_birth) deceased.dateOfBirth = fields.date_of_birth;
  else if (age !== undefined && age >= 12 && age <= 119) deceased.ageInYears = age;
  const answers: SubmissionData = {};
  if (fields.informant_name) answers.Id10007 = fields.informant_name;
  if (fields.father_name) answers.Id10061 = fields.father_name;
  if (fields.mother_name) answers.Id10062 = fields.mother_name;
  return { deceased: deceased as Prefill["deceased"], answers, lockedQuestionNames: [] };
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
  params: { siteId?: string; orgUnitId?: string; deathId?: string; clientDeathId?: string }
): Promise<DraftHost | "completed" | undefined> {
  const row = await getDraftRow(db, draftId);
  if (row?.completed) return "completed";
  if (row) {
    const prefill = await getDraftPrefill<Prefill>(db, draftId);
    return { siteId: row.site_id, orgUnitId: row.org_unit_id ?? undefined, binding: {}, prefill };
  }
  if (params.deathId) {
    const found = await getCase(db, params.deathId);
    if (!found) return undefined;
    return {
      siteId: found.site_id,
      orgUnitId: found.org_unit_id ?? undefined,
      binding: { deathId: found.death_id, uniqueId: found.unique_id, prefill: found.prefill },
      prefill: found.prefill
    };
  }
  if (params.clientDeathId) {
    const reg = await getRegistration(db, params.clientDeathId);
    if (!reg) return undefined;
    const prefill = prefillFromRegistration(reg.fields);
    return {
      siteId: reg.site_id,
      orgUnitId: reg.org_unit_id ?? undefined,
      binding: { clientDeathId: reg.client_death_id, prefill },
      prefill
    };
  }
  return params.siteId ? { siteId: params.siteId, orgUnitId: params.orgUnitId, binding: {} } : undefined;
}
