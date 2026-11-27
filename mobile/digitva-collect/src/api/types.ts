/** Response shapes and validating parsers of the DigitVA API; the transport stays in ../api.ts. */
import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";
import { ApiError } from "../api";
import type { CaseIdentifier } from "../identifiers";

export interface AccessUnit {
  org_unit_id: string;
  unit_code: string;
  unit_name: string;
  level_code: string;
  path: string;
  is_active: boolean;
  selectable: boolean;
  roles: string[];
  can_code: boolean;
}

export interface AccessProject {
  project_id: string;
  project_name: string;
  has_tree: boolean;
  settings?: {
    web_intake_mode: "off" | "direct" | "death_register" | "both";
    coding_scope: { level_code: string; above_mode: string } | null;
  };
  /** Server rule: supervisor here and the project registers deaths (mode death_register or both). */
  supervises_deaths?: boolean;
  grants: Array<{ role: string; scope: string; site_id?: string; org_unit_id?: string; unit_name?: string; codes?: boolean; active: boolean; source: "assigned" | "self_coding" }>;
  sites: Array<{ site_id: string; site_name: string; roles: string[] }>;
  /**
   * `code` and `review` are the server's per-action reach (`authz.predicates.action_reach`), present only where the user
   * holds that action in the project; absent from older servers, and dropped by the parser when malformed. Other reach
   * keys the server sends are not read here.
   */
  actions: { interview: AccessActionContext[]; register_death: AccessActionContext[]; code?: ActionReach; review?: ActionReach };
  /** Exact SmartVA snapshot for authorized interview site/unit targets. */
  smartva_targets?: SmartVaTarget[];
  /** Project-owned self-coding setting; absent on older servers/fixtures. */
  self_coding?: {
    enabled: boolean;
    code_now?: boolean;
    /** Absent on older servers; local ICD-11 editing requires this explicit projection. */
    offline_coding?: {
      enabled: boolean;
      project_mode: string;
      icd_classification: string;
      /** Additive (digitva-p8uj); absent on older servers: offline coding then asks neither. */
      narrative_qa_enabled?: boolean;
      social_autopsy_enabled?: boolean;
    };
  };
  units?: AccessUnit[];
  levels?: Array<{ level_code: string; level_name: string; depth: number }>;
}

export interface SmartVaTarget {
  schema_version: 1;
  site_id: string;
  org_unit_id: string | null;
  form_id: string;
  form_updated_at: string;
  options: { country: string; hiv: boolean; malaria: boolean; hce: boolean; freetext: boolean };
  options_digest: `sha256:${string}`;
}

/** Where an action's grants reach in one project: the whole project, these sites, or these units and their subtrees. */
export interface ActionReach {
  project: boolean;
  site_ids: string[];
  org_unit_ids: string[];
}

export interface AccessActionContext {
    site_id: string;
    site_name: string;
    web_intake_mode: "direct" | "death_register" | "both";
    org_units: Array<{ org_unit_id: string; unit_code: string; unit_name: string; path: string }>;
}

function isAccessActionContext(entry: unknown): entry is AccessActionContext {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  return record(entry) && typeof entry.site_id === "string" && typeof entry.site_name === "string" &&
    ["direct", "death_register", "both"].includes(String(entry.web_intake_mode)) && Array.isArray(entry.org_units) &&
    entry.org_units.every((unit) => record(unit) &&
      ["org_unit_id", "unit_code", "unit_name", "path"].every((field) => typeof unit[field] === "string"));
}

export function isSmartVaTarget(value: unknown): value is SmartVaTarget {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const target = value as Record<string, unknown>;
  const options = target.options;
  const timestamp = target.form_updated_at;
  return target.schema_version === 1 && typeof target.site_id === "string" && target.site_id.length > 0 &&
    (target.org_unit_id === null || (typeof target.org_unit_id === "string" && target.org_unit_id.length > 0)) &&
    typeof target.form_id === "string" && target.form_id.length > 0 && typeof timestamp === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(timestamp) &&
    Number.isFinite(Date.parse(timestamp)) && typeof options === "object" && options !== null && !Array.isArray(options) &&
    typeof (options as Record<string, unknown>).country === "string" && !!(options as Record<string, unknown>).country &&
    ["hiv", "malaria", "hce", "freetext"].every((key) => typeof (options as Record<string, unknown>)[key] === "boolean") &&
    typeof target.options_digest === "string" && /^sha256:[a-f0-9]{64}$/.test(target.options_digest);
}

/** The Training sub-menus (docs/policy/training-demo-project.md); each opens for the training roles listed there. */
export type TrainingArea = "interview" | "coding" | "review";

/**
 * The Training menu's data. `null`/absent when training is off. The normal `projects` and `roles` leave the training
 * project out; `project` carries the user's grants in it (shaped like a `projects` entry) for the Training screens.
 */
export interface TrainingAccess {
  project_id: string | null;
  areas: TrainingArea[];
  pending: boolean;
  /** The types of the user's active sessions (null for a legacy one); absent from older servers. */
  session_types?: (string | null)[];
  project?: AccessProject | null;
}

export interface AccessSummary {
  user: { user_id: string; name: string; coding_languages?: string[] };
  is_admin: boolean;
  roles: string[];
  demo_coding: { available: boolean; project_ids: string[] };
  projects: AccessProject[];
  training?: TrainingAccess | null;
  account?: {
    privileged?: boolean;
    pii_visible?: boolean;
    device_access?: boolean;
    mentor?: {
      member: boolean;
      admin_of: Array<{ institute_code: string; institute_name: string }>;
    };
  };
}

/** Validate the access boundary before using server data to gate screens or pickers. */
export function parseAccessSummary(value: unknown): AccessSummary {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const strings = (item: unknown): item is string[] => Array.isArray(item) && item.every((part) => typeof part === "string");
  if (!record(value) || !record(value.user) || typeof value.user.user_id !== "string" || typeof value.user.name !== "string" ||
      typeof value.is_admin !== "boolean" || !record(value.demo_coding) || typeof value.demo_coding.available !== "boolean" ||
      !strings(value.roles) || !strings(value.demo_coding.project_ids) || !Array.isArray(value.projects)) throw new ApiError(200, "malformed_response");
  if (value.user.coding_languages !== undefined && !strings(value.user.coding_languages)) throw new ApiError(200, "malformed_response");
  for (const project of value.projects) {
    if (!record(project) || typeof project.project_id !== "string" || typeof project.project_name !== "string" ||
        typeof project.has_tree !== "boolean" || !Array.isArray(project.grants) || !Array.isArray(project.sites) ||
        !record(project.actions) || !Array.isArray(project.actions.interview) || !Array.isArray(project.actions.register_death)) throw new ApiError(200, "malformed_response");
    if (project.settings !== undefined &&
        (!record(project.settings) || !["off", "direct", "death_register", "both"].includes(String(project.settings.web_intake_mode)) ||
          !(project.settings.coding_scope === null || (record(project.settings.coding_scope) &&
            typeof project.settings.coding_scope.level_code === "string" && typeof project.settings.coding_scope.above_mode === "string")))) {
      throw new ApiError(200, "malformed_response");
    }
    if (project.self_coding !== undefined &&
        (!record(project.self_coding) || typeof project.self_coding.enabled !== "boolean" ||
          (project.self_coding.code_now !== undefined && typeof project.self_coding.code_now !== "boolean"))) {
      throw new ApiError(200, "malformed_response");
    }
    if (project.smartva_targets !== undefined &&
        (!Array.isArray(project.smartva_targets) || !project.smartva_targets.every(isSmartVaTarget))) {
      throw new ApiError(200, "malformed_response");
    }
    if (record(project.self_coding) && project.self_coding.offline_coding !== undefined &&
        (!record(project.self_coding.offline_coding) ||
          typeof project.self_coding.offline_coding.enabled !== "boolean" ||
          typeof project.self_coding.offline_coding.project_mode !== "string" ||
          typeof project.self_coding.offline_coding.icd_classification !== "string" ||
          !["boolean", "undefined"].includes(typeof project.self_coding.offline_coding.narrative_qa_enabled) ||
          !["boolean", "undefined"].includes(typeof project.self_coding.offline_coding.social_autopsy_enabled))) {
      throw new ApiError(200, "malformed_response");
    }
    for (const grant of project.grants) {
      if (!record(grant) || typeof grant.role !== "string" || !["project", "project_site", "org_unit"].includes(String(grant.scope)) ||
          typeof grant.active !== "boolean" || !["assigned", "self_coding"].includes(String(grant.source)) ||
          (grant.scope === "project_site" && typeof grant.site_id !== "string") ||
          (grant.scope === "org_unit" && (typeof grant.org_unit_id !== "string" || typeof grant.unit_name !== "string")) ||
          (["coder", "coding_tester", "reviewer"].includes(grant.role) && typeof grant.codes !== "boolean")) throw new ApiError(200, "malformed_response");
    }
    for (const entry of project.actions.interview) {
      if (!isAccessActionContext(entry)) throw new ApiError(200, "malformed_response");
    }
    for (const entry of project.actions.register_death) {
      if (!isAccessActionContext(entry)) throw new ApiError(200, "malformed_response");
    }
    // Advisory only (it builds the queue's "Site and unit" choices, never a gate): a malformed reach is dropped, never
    // thrown, since a throw here revokes every capability the account holds on the phone.
    for (const key of ["code", "review"] as const) {
      const reach = project.actions[key];
      if (reach !== undefined && (!record(reach) || typeof reach.project !== "boolean" || !strings(reach.site_ids) || !strings(reach.org_unit_ids))) {
        delete project.actions[key];
      }
    }
    for (const site of project.sites) {
      if (!record(site) || typeof site.site_id !== "string" || typeof site.site_name !== "string" || !strings(site.roles)) throw new ApiError(200, "malformed_response");
    }
    if (project.has_tree && (!Array.isArray(project.units) || !Array.isArray(project.levels))) throw new ApiError(200, "malformed_response");
    if (Array.isArray(project.units)) for (const unit of project.units) {
      if (!record(unit) || !["org_unit_id", "unit_code", "unit_name", "level_code", "path"].every((field) => typeof unit[field] === "string") ||
          !strings(unit.roles) || typeof unit.selectable !== "boolean" || typeof unit.can_code !== "boolean" || typeof unit.is_active !== "boolean") throw new ApiError(200, "malformed_response");
    }
    if (Array.isArray(project.levels)) for (const level of project.levels) {
      if (!record(level) || typeof level.level_code !== "string" || typeof level.level_name !== "string" || typeof level.depth !== "number") throw new ApiError(200, "malformed_response");
    }
    if (Array.isArray(project.smartva_targets)) {
      const seenTargets = new Set<string>();
      for (const target of project.smartva_targets as SmartVaTarget[]) {
        const action = (project.actions.interview as AccessActionContext[]).find((entry) => entry.site_id === target.site_id);
        const targetKey = `${target.site_id}:${target.org_unit_id ?? "-"}`;
        if (!action || seenTargets.has(targetKey)) throw new ApiError(200, "malformed_response");
        seenTargets.add(targetKey);
        if (!project.has_tree) {
          if (target.org_unit_id !== null) throw new ApiError(200, "malformed_response");
          continue;
        }
        if (target.org_unit_id === null || !Array.isArray(project.units)) throw new ApiError(200, "malformed_response");
        const unit = (project.units as Array<Record<string, unknown>>).find((entry) =>
          entry.org_unit_id === target.org_unit_id && entry.selectable === true && Array.isArray(entry.roles) && entry.roles.includes("interviewer"));
        const roots = action.org_units;
        if (!unit || (roots.length > 0 &&
            !roots.some((root) => unit.path === root.path || String(unit.path).startsWith(`${root.path}.`)))) {
          throw new ApiError(200, "malformed_response");
        }
      }
    }
  }
  if (value.training !== undefined && value.training !== null) {
    const training = value.training;
    if (!record(training) || !strings(training.areas) || typeof training.pending !== "boolean" ||
        !(training.project_id === null || typeof training.project_id === "string") ||
        !(training.project === undefined || training.project === null || record(training.project))) throw new ApiError(200, "malformed_response");
  }
  if (value.account !== undefined) {
    if (!record(value.account)) throw new ApiError(200, "malformed_response");
    if (value.account.mentor !== undefined) {
      if (
        !record(value.account.mentor) ||
        typeof value.account.mentor.member !== "boolean" ||
        !Array.isArray(value.account.mentor.admin_of)
      ) {
        throw new ApiError(200, "malformed_response");
      }
      for (const inst of value.account.mentor.admin_of) {
        if (
          !record(inst) ||
          typeof inst.institute_code !== "string" ||
          typeof inst.institute_name !== "string"
        ) {
          throw new ApiError(200, "malformed_response");
        }
      }
    }
  }
  return value as unknown as AccessSummary;
}

/** Roles the supervision API admits (the server re-checks each supervised case). */
export const SUPERVISION_ROLES = ["interview_supervisor", "data_manager"];

/** Navigation is advisory; each action remains authorised by the server. */
export function accessCapabilities(access: AccessSummary): ClientBootstrap["capabilities"] {
  const hasMentoring = Boolean(access.account?.mentor?.member || (access.account?.mentor?.admin_of?.length ?? 0) > 0);
  return {
    intake: access.projects.some((project) => project.actions.interview.length > 0),
    registerDeath: access.projects.some((project) => project.actions.register_death.length > 0),
    registeredDeaths: access.roles.includes("death_reporter"),
    coding: access.roles.some((role) => ["coder", "coding_tester"].includes(role)) || access.demo_coding.available,
    reviewing: access.roles.includes("reviewer"),
    // Supervisors see Deaths only where deaths are registered (a direct-only project has no register).
    supervision: access.projects.some((project) => project.supervises_deaths === true),
    ...(hasMentoring ? { mentoring: true } : {}),
  };
}

/** Expand server interview roots in tree order and retain their ancestor context. */
/** Which projects a context reads: the normal ones (never the training project), only the training one, or both (by-id screens). */
export type IntakeScope = "normal" | "training" | "all";

export function intakeContextFromAccess(
  access: AccessSummary,
  action: "interview" | "register_death" = "interview",
  scope: IntakeScope = "normal",
): IntakeContextEntry[] {
  const training = access.training?.project ? [access.training.project] : [];
  const projects = scope === "training" ? training : scope === "all" ? [...access.projects, ...training] : access.projects;
  return projects.flatMap((project) => project.actions[action].map((entry) => {
    const roots = entry.org_units;
    const units = project.units?.filter((unit) => !roots.length || roots.some((root) =>
      unit.path === root.path || unit.path.startsWith(`${root.path}.`) || root.path.startsWith(`${unit.path}.`),
    )).map((unit) => roots.length ? ({
      ...unit,
      selectable: unit.selectable && roots.some((root) => unit.path === root.path || unit.path.startsWith(`${root.path}.`)),
    }) : unit);
    return {
      project_id: project.project_id, project_name: project.project_name, site_id: entry.site_id,
      site_name: entry.site_name, web_intake_mode: entry.web_intake_mode,
      org_units: units ?? roots.map((unit) => ({ ...unit, selectable: true })),
    };
  }));
}

/** Check a registration target against the interview context before offering start-interview. */
export function hasInterviewRegistrationAccess(
  access: AccessSummary,
  projectId: string,
  siteId: string,
  orgUnitId?: string,
): boolean {
  const project = [...access.projects, ...(access.training?.project ? [access.training.project] : [])]
    .find((entry) => entry.project_id === projectId);
  return Boolean(project?.actions.interview.some((entry) => {
    if (entry.site_id !== siteId) return false;
    if (!orgUnitId || entry.org_units.length === 0) return true;
    const unit = project.units?.find((item) => item.org_unit_id === orgUnitId);
    return Boolean(unit && entry.org_units.some((root) =>
      unit.path === root.path || unit.path.startsWith(`${root.path}.`),
    ));
  }));
}

export interface ClientCsrf {
  header: string;
  token: string;
  /** Set by the Training screens' bootstrap: every write asks for the training scope (`?training=1`). */
  training?: true;
}

export interface ClientLinks {
  login: string;
  logout: string;
  intakeCases: string;
  intakeDrafts: string;
  coding?: string;
  reviewing?: string;
}

export interface ClientBootstrap {
  user: { user_id: string; name: string };
  csrf: ClientCsrf;
  capabilities: {
    intake: boolean;
    registerDeath: boolean;
    registeredDeaths: boolean;
    coding: boolean;
    reviewing: boolean;
    supervision: boolean;
    mentoring?: boolean;
  };
  access: AccessSummary;
  links: ClientLinks;
  /** Set by the Training screens' derived bootstrap (training.ts `trainingBootstrap`): lists ask for `training=1`. */
  scope?: "training";
}

export interface AuthenticationRequired {
  authenticated: false;
  loginUrl: string;
  actionCode?: "terms_required";
  csrf?: ClientCsrf;
}

export interface AuthenticatedBootstrap {
  authenticated: true;
  bootstrap: ClientBootstrap;
}

export type BootstrapResult = AuthenticationRequired | AuthenticatedBootstrap;


export interface IntakeContextEntry {
  project_id: string;
  project_name?: string;
  site_id: string;
  site_name?: string;
  web_intake_mode?: string;
  org_units?: Array<{
    org_unit_id: string;
    unit_code?: string;
    unit_name?: string;
    level_code?: string;
    level_name?: string;
    path?: string;
    is_active?: boolean;
    selectable?: boolean;
  }>;
}

export interface FormOptions {
  web_intake_mode?: "off" | "direct" | "death_register" | "both";
  instrument_version?: string | null;
  definition_sha256?: string | null;
  narration_languages?: Array<{ code: string; label: string }>;
  project_id?: string;
  enabled_extensions?: string[];
  form_types?: Array<{ instrument_code: string | null; is_default: boolean }>;
  available_locales?: Array<{
    code: string;
    label: string;
    under_review?: boolean;
  }>;
  default_locale?: string;
  translation_versions?: Record<string, number>;
  intake_note?: string | null;
}

export interface IntakeBootstrap {
  user?: { user_id: string; name: string };
  context: IntakeContextEntry[];
  form_options?: FormOptions;
  instrument_version?: string;
  /** Server-provided action links; callers must not reconstruct prefixed paths. */
  links?: { deaths?: string; drafts?: string; cases?: string };
}

export interface CaseRow {
  death_id: string;
  unique_id: string;
  deceased_name?: string;
  deceased_sex?: string;
  date_of_death?: string;
  age_years?: number | null;
  status?: string;
  state?: string;
  project_id?: string;
  site_id?: string;
  site_name?: string;
  org_unit_id?: string | null;
  org_unit_name?: string | null;
  unit_name?: string | null;
  has_informant_phone?: boolean;
  has_informant_phone_2?: boolean;
  /** Death-site GPS fix: on the register list, and on GET /intake/cases rows only for a caller who may see it (else absent). */
  latitude?: number | null;
  longitude?: number | null;
  accuracy_m?: number | null;
  last_contact_at?: string | null;
  next_visit_at?: string | null;
  my_draft_id?: string | null;
  other_draft_active?: boolean;
  other_draft_started_at?: string | null;
  /** Name of the interviewer whose open draft started earliest (owner, 2026-11-05); absent from older servers. */
  other_draft_started_by?: string | null;
  other_complete_interview?: boolean;
  code_now?: boolean;
  /** Coding state of the case's submission (GET /intake/cases); null or absent before a submission. */
  coding_status?: "awaiting_coding" | "in_coding" | "coded" | "not_codeable" | null;
  /** The caller registered this death (GET /intake/cases). */
  registered_by_me?: boolean;
  /** False for a death the caller reaches only as its death_reporter: no interview or case detail. */
  can_interview?: boolean;
  created_at?: string;
  updated_at?: string;
  /** Registration numbers: `value` for viewers who may see it, `present` for badge-only viewers. */
  identifiers?: CaseIdentifier[];
  /** The server's verdict on the any-time number write for this caller and case; absent means no. */
  can_edit_identifiers?: boolean;
  [key: string]: unknown;
}

export interface RegisteredDeathPage {
  deaths: CaseRow[];
  next_cursor: string | null;
}

/** Validate the server-owned shape used by the own-registration list. */
export function parseRegisteredDeathPage(value: unknown): RegisteredDeathPage {
  const record = (item: unknown): item is Record<string, unknown> => !!item && typeof item === "object" && !Array.isArray(item);
  const optionalString = (item: Record<string, unknown>, key: string) => item[key] === undefined || typeof item[key] === "string";
  const optionalNullableString = (item: Record<string, unknown>, key: string) => item[key] === undefined || item[key] === null || typeof item[key] === "string";
  if (!record(value) || !Array.isArray(value.deaths) ||
      !(value.next_cursor === null || typeof value.next_cursor === "string")) {
    throw new ApiError(200, "malformed_response");
  }
  const deathIds = new Set<string>();
  for (const death of value.deaths) {
    if (!record(death) || typeof death.death_id !== "string" || !death.death_id.trim() ||
        typeof death.unique_id !== "string" || !death.unique_id.trim() || deathIds.has(death.death_id) ||
        !["status", "state", "project_id", "site_id"]
          .every((key) => optionalString(death, key)) ||
        !["deceased_name", "deceased_sex", "date_of_death", "site_name", "unit_name", "org_unit_name", "org_unit_id", "last_contact_at", "next_visit_at", "updated_at"]
          .every((key) => optionalNullableString(death, key)) ||
        !(death.age_years === undefined || death.age_years === null ||
          (typeof death.age_years === "number" && Number.isFinite(death.age_years)))) {
      throw new ApiError(200, "malformed_response");
    }
    deathIds.add(death.death_id);
  }
  return { deaths: value.deaths as CaseRow[], next_cursor: value.next_cursor as string | null };
}

export interface CaseDetailDeceased {
  name?: string | null;
  sex?: string | null;
  age_years?: number | null;
  date_of_birth?: string | null;
  date_of_birth_partial?: string | null;
  date_of_death?: string | null;
  place_of_death?: string | null;
}

export interface CaseDetailAddress {
  address?: string | null;
  house_street?: string | null;
  village_ward?: string | null;
  landmark?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  accuracy_m?: number | null;
  captured_at?: string | null;
}

export interface CaseDetailInformant {
  name?: string | null;
  phone?: string | null;
  phone_2?: string | null;
}

export interface CaseDetailLinks {
  self?: string;
  attempts?: string;
  visit?: string;
  start_interview?: string;
  form?: string;
}

export interface CaseDetail extends CaseRow {
  prefill?: Record<string, unknown>;
  deceased?: CaseDetailDeceased | null;
  household_address?: CaseDetailAddress | null;
  informant?: CaseDetailInformant | null;
  remarks?: string | null;
  details_pending?: boolean;
  pending_flag?: string | null;
  registered_by_me?: boolean;
  started_by_me?: boolean;
  va_sid?: string | null;
  created_at?: string;
  updated_at?: string;
  links?: CaseDetailLinks;
}

export interface DraftSummary {
  draft_id: string;
  unique_id?: string;
  project_id: string;
  site_id: string;
  site_name?: string;
  org_unit_id?: string | null;
  org_unit_name?: string | null;
  death_id?: string | null;
  status?: string;
  current_section?: string | null;
  updated_at?: string;
  /** List rows only (`GET /drafts`): the case's name and the count of saved sections. */
  deceased_name?: string | null;
  sections_saved?: number;
  deceased_sex?: string | null;
  age_years?: number | null;
  date_of_death?: string | null;
  created_at?: string;
  [key: string]: unknown;
}

export interface DraftEnvelope extends WhoVaDraft {
  data: SubmissionData;
  locale?: string;
  translation_version?: number;
}

/**
 * Who last changed a draft (`last_change` of `GET /intake/drafts/<id>` and of a 409 `draft_stale`): `via` and
 * `by_you`/`name` are null when the server did not record that version; `name` is a display name only.
 */
export interface DraftLastChange {
  at: string;
  via: "phone" | "browser" | null;
  by_you: boolean | null;
  name: string | null;
  refusal: boolean;
}

/** The optional `last_change` of a reply or refusal payload, when it has the expected shape. */
export function readLastChange(value: unknown): DraftLastChange | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
  const change = value as Record<string, unknown>;
  if (typeof change.at !== "string" || Number.isNaN(Date.parse(change.at))) return undefined;
  return {
    at: change.at,
    via: change.via === "phone" || change.via === "browser" ? change.via : null,
    by_you: typeof change.by_you === "boolean" ? change.by_you : null,
    name: typeof change.name === "string" && change.name.trim() ? change.name.trim().slice(0, 128) : null,
    refusal: change.refusal === true,
  };
}

export interface DraftResponse {
  draft: DraftSummary;
  envelope: DraftEnvelope;
  prefill: Record<string, unknown>;
  last_change?: DraftLastChange;
}

export interface RegistrationInput {
  project_id: string;
  site_id: string;
  org_unit_id?: string;
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
  father_name?: string;
  mother_name?: string;
  informant_phone?: string;
  informant_phone_2?: string;
  remarks?: string;
  /** {type code: text}; on a correction null clears one. */
  identifiers?: Record<string, string | null>;
}


/** A live native device session, with no credentials or other sensitive fields. */
export interface AccountDevice {
  device_id: string;
  name: string;
  platform: string;
  app_version: string | null;
  enrolled_at: string;
  last_seen_at: string | null;
  current: boolean;
}

export interface AccountDevicesResponse {
  devices: AccountDevice[];
}

export interface DeviceDecommissionResponse {
  decommissioned: boolean;
  sessions_ended: number;
  current: boolean;
}

/** GET /api/v1/me/home: one Home block per role held, counts only (docs/current-state/api-v1.md). */
export interface HomeBlocks {
  death_reporter?: { registered: number; awaiting_interview: number };
  interviewer?: { drafts_in_progress: number; needing_visit: number };
  interview_supervisor?: { flagged: number; needs_decision: number; open: number; submitted: number };
  /** `practice`: a coding tester without a coder grant; `completed` and `recodeable` are then absent. */
  coder?: { ready: number; practice: boolean; completed?: number; recodeable?: number };
  reviewer?: { available: number; completed: number };
  data_manager?: { screening_pending: number; ready_for_coding: number; not_codeable: number };
  /** No counts: the client loads /api/v1/me/kpis when the block is opened. */
  progress?: { roles: string[] };
}

export interface HomeSummary {
  roles: string[];
  blocks: HomeBlocks;
}
