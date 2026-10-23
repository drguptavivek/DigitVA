/**
 * Respondent consent on the phone (docs/policy/respondent-consent-notice-draft.md, "Phone flow").
 *
 * The project's consent settings (notice texts, purposes, covered fields) are cached per project in the
 * interviewer's encrypted store at every sync, so the consent screen works offline. A decision is stored
 * beside what it covers and travels with it: a registration's with POST /deaths, an interview's with
 * POST /submissions (same envelope as the web, contract 5.3). Never logged; the error log gets Ref lines only.
 */
import { INTAKE_API } from "./api";
import { authedRequest, SessionRevokedError, SignInRequiredError } from "./auth";
import {
  INFORMANT_PII_FIELDS,
  normaliseProjectConsentConfig,
  selectActiveNoticeVersion,
  type ConsentRecordEnvelope,
  type ProjectConsentConfig,
} from "./consent";
import { getMeta, setMeta, type Db } from "./drafts";

const CONFIG_KEY = "consentConfig";

/**
 * The questions and register fields locked empty when there is no consent. Equal to the server's
 * `consent_service.DEFAULT_COVERED_FIELDS`: the informant's details, the respondent's name, and the family
 * and address data the register prefills.
 */
export const DEFAULT_COVERED_FIELDS: readonly string[] = [
  ...INFORMANT_PII_FIELDS, "father_name", "mother_name", "Id10007", "Id10055", "Id10057", "Id10061", "Id10062",
];

/** The cached notice's covered fields (what the server enforces), else the built-in list. */
export function coveredFieldsOf(config: ProjectConsentConfig | undefined): string[] {
  return [...(config ? selectActiveNoticeVersion(config)?.covered_fields ?? DEFAULT_COVERED_FIELDS : DEFAULT_COVERED_FIELDS)];
}

/** A decision as kept on the phone: the envelope sent to the server, plus what it covers and who took it. */
export interface StoredConsent {
  envelope: ConsentRecordEnvelope;
  project_id: string;
  /** The notice version's covered fields, so a refusal can strip them with no config at hand. */
  covered_fields: string[];
  recorded_by: string;
}

/** Cache the project's consent settings; best effort like the identifier types (a failure keeps the old copy, session errors propagate). */
export async function refreshConsentConfig(userId: string, db: Db, projectId: string): Promise<ProjectConsentConfig | undefined> {
  try {
    const { body } = await authedRequest<unknown>(userId, `${INTAKE_API}/consent-config?project_id=${encodeURIComponent(projectId)}`);
    const config = normaliseProjectConsentConfig(body);
    if (!config) return undefined;
    await setMeta(db, CONFIG_KEY, config, projectId);
    return config;
  } catch (error) {
    if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) throw error;
    return undefined;
  }
}

export function getConsentConfig(db: Db, projectId: string): Promise<ProjectConsentConfig | undefined> {
  return getMeta<ProjectConsentConfig>(db, CONFIG_KEY, projectId);
}

/** Whether the cached settings can be used at all: known, and a refusal behaviour this app understands. */
function usable(config: ProjectConsentConfig | undefined): config is ProjectConsentConfig {
  return !!config && (!config.refusal_behaviour || config.refusal_behaviour === "interview_without_informant_data");
}

/**
 * What an interview must do about consent. `off`: the project does not require it. `ask`: show the notice.
 * `unavailable`: consent is required (or unknown) but no usable notice is cached, so the covered fields stay
 * locked empty and the interviewer is told why.
 */
export type InterviewConsentGate =
  | { state: "off" }
  | { state: "ask"; config: ProjectConsentConfig }
  | { state: "unavailable"; covered: string[] };

export function interviewConsentGate(config: ProjectConsentConfig | undefined): InterviewConsentGate {
  if (!usable(config)) return { state: "unavailable", covered: [...DEFAULT_COVERED_FIELDS] };
  if (!config.consent_required) return { state: "off" };
  const notice = selectActiveNoticeVersion(config);
  return notice ? { state: "ask", config } : { state: "unavailable", covered: [...DEFAULT_COVERED_FIELDS] };
}

/** Informant details on the phone always need a granted consent (owner 2026-10-22): `ask` when a notice is usable, else `unavailable`. */
export function registrationConsentGate(config: ProjectConsentConfig | undefined): { state: "ask"; config: ProjectConsentConfig } | { state: "unavailable" } {
  return usable(config) && selectActiveNoticeVersion(config) ? { state: "ask", config } : { state: "unavailable" };
}

const draftKey = (draftId: string) => `consent:draft:${draftId}`;
const registrationKey = (clientDeathId: string) => `consent:reg:${clientDeathId}`;
const deathKey = (deathId: string) => `consent:death:${deathId}`;

/** Keep a decision with the notice's covered fields. */
export function storedConsent(envelope: ConsentRecordEnvelope, config: ProjectConsentConfig, userId: string): StoredConsent {
  const notice = config.notice_versions.find((version) => version.notice_version_id === envelope.notice_version_id);
  return { envelope, project_id: config.project_id, covered_fields: [...(notice?.covered_fields ?? DEFAULT_COVERED_FIELDS)], recorded_by: userId };
}

const refusedInheritedKey = (draftId: string) => `consentRefused:${draftId}`;

export async function saveDraftConsent(db: Db, draftId: string, record: StoredConsent): Promise<void> {
  await setMeta(db, draftKey(draftId), record);
  await db.runAsync("DELETE FROM meta WHERE key = ?", [refusedInheritedKey(draftId)]);
}
export const saveRegistrationConsent = (db: Db, clientDeathId: string, record: StoredConsent) => setMeta(db, registrationKey(clientDeathId), record);
export const getRegistrationConsent = (db: Db, clientDeathId: string) => getMeta<StoredConsent>(db, registrationKey(clientDeathId));

export type ConsentIndex = Map<string, StoredConsent>;

/** Every stored decision in one read (the upload loop and the screens look decisions up in memory, never per item). */
export async function loadConsents(db: Db): Promise<ConsentIndex> {
  const rows = await db.getAllAsync<{ key: string; value: string }>("SELECT key, value FROM meta WHERE key LIKE ?", ["consent:%"]);
  const found: ConsentIndex = new Map();
  for (const { key, value } of rows) {
    try { found.set(key, JSON.parse(value) as StoredConsent); } catch { /* unreadable: the server asks again */ }
  }
  return found;
}

/** The decision that applies to a draft: its own, else its registration's (on this phone, before or after the server accepted it). */
export function consentFor(
  index: ConsentIndex,
  draft: { id: string; death_id?: string | null; client_death_id?: string | null },
): { record: StoredConsent; own: boolean } | undefined {
  const own = index.get(draftKey(draft.id));
  if (own) return { record: own, own: true };
  const inherited = (draft.client_death_id && index.get(registrationKey(draft.client_death_id))) ||
    (draft.death_id && index.get(deathKey(draft.death_id))) || undefined;
  return inherited ? { record: inherited, own: false } : undefined;
}

export async function consentForDraft(db: Db, draft: Parameters<typeof consentFor>[1]) {
  return consentFor(await loadConsents(db), draft);
}

/** Forget a draft's own decision so the form asks again (the server refused it as unusable). */
export async function deleteDraftConsent(db: Db, draftId: string): Promise<void> {
  await db.runAsync("DELETE FROM meta WHERE key = ?", [draftKey(draftId)]);
}

/**
 * The server refused the decision this draft inherited from its registration (consent:reg / consent:death).
 * That record is shared, so it stays; the draft is flagged so its form asks for a new attempt-level decision.
 */
export const markInheritedConsentRefused = (db: Db, draftId: string) => setMeta(db, refusedInheritedKey(draftId), true);
export async function inheritedConsentRefused(db: Db, draftId: string): Promise<boolean> {
  return (await getMeta<boolean>(db, refusedInheritedKey(draftId))) === true;
}

/** `data` without the covered answers (a refusal never sends them); the same object when nothing is covered. */
export function withoutCovered<T extends object>(data: T, covered: readonly string[]): T {
  if (!covered.some((name) => name in data)) return data;
  return Object.fromEntries(Object.entries(data).filter(([name]) => !covered.includes(name))) as T;
}
