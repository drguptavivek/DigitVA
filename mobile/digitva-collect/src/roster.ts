import { requestClientJson, type ClientCsrf } from "./api";

export type ActingRole =
  | "death_reporter"
  | "interviewer"
  | "station_supervisor"
  | "coder";

export type LegacyActingRole = ActingRole | "reporter" | "supervisor";

export interface StationRosterRoleScope {
  role: ActingRole;
  project_id: string;
  site_id: string;
  org_unit_id?: string | null;
}

export interface StationRosterMember {
  user_id: number | null;
  member_id: string;
  name: string;
  designation: string;
  roles?: StationRosterRoleScope[];
  is_reporter: boolean;
  is_interviewer: boolean;
  is_supervisor: boolean;
  is_coder: boolean;
  active: boolean;
  source: "sandbox" | "provisioned";
  created_at: string;
  updated_at: string;
}

export interface DesignationOption {
  code: string;
  label: string;
}

export interface StationCustodian {
  name: string;
  designation: string;
  phone?: string | null;
  email?: string | null;
  onboarded_on: string;
  verified_by_user_id?: number;
}

export interface ActiveActorContext {
  user_id?: number | null;
  member_id: string;
  name: string;
  designation: string;
  acting_role: ActingRole;
  allowed_acting_roles: ActingRole[];
}

export interface RosterAuditEntry {
  audit_id: number;
  action: string;
  target_member_id?: string | null;
  actor_member_id?: string | null;
  actor_name: string;
  acting_role: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface StationRosterSnapshot {
  station_mode: "standalone" | "provisioned";
  editable: boolean;
  station_config_id?: string | null;
  config_expires_at?: string | null;
  custodian: StationCustodian | null;
  designations: DesignationOption[];
  members: StationRosterMember[];
  active_actor: ActiveActorContext;
  recent_audit: RosterAuditEntry[];
  purge?: string[];
}

export interface UpsertRosterMemberInput {
  member_id?: string;
  user_id?: number | null;
  name: string;
  designation: string;
  is_reporter: boolean;
  is_interviewer: boolean;
  is_supervisor: boolean;
  is_coder: boolean;
  active: boolean;
}

export const ACTING_ROLE_LABELS: Record<ActingRole, string> = {
  death_reporter: "Death Reporter",
  interviewer: "Interviewer",
  station_supervisor: "Station Supervisor",
  coder: "Coder (Masked)",
};

export const DEFAULT_DESIGNATIONS: DesignationOption[] = [
  { code: "medical_officer", label: "Medical Officer" },
  { code: "health_supervisor", label: "Health Supervisor" },
  { code: "health_worker", label: "Health Worker / ANM / MPW" },
  { code: "other", label: "Other" },
];

export function normaliseActingRole(role: string | null | undefined): ActingRole {
  const cleaned = String(role ?? "").trim().toLowerCase();
  if (cleaned === "reporter" || cleaned === "death_reporter") {
    return "death_reporter";
  }
  if (cleaned === "supervisor" || cleaned === "station_supervisor") {
    return "station_supervisor";
  }
  if (cleaned === "coder") {
    return "coder";
  }
  return "interviewer";
}

function slugifyDesignationCode(label: string): string {
  return (
    label
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "") || "other"
  );
}

export function normaliseDesignations(
  raw: ReadonlyArray<string | DesignationOption> | null | undefined,
): DesignationOption[] {
  if (!Array.isArray(raw) || raw.length === 0) {
    return DEFAULT_DESIGNATIONS.map((d) => ({ ...d }));
  }
  const out: DesignationOption[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    if (typeof item === "string") {
      const label = item.trim();
      if (!label) continue;
      const preset = DEFAULT_DESIGNATIONS.find(
        (d) => d.code === label.toLowerCase() || d.label.toLowerCase() === label.toLowerCase(),
      );
      const code = preset ? preset.code : slugifyDesignationCode(label);
      if (!seen.has(code)) {
        seen.add(code);
        out.push({ code, label: preset ? preset.label : label });
      }
    } else if (item && typeof item === "object") {
      const code = String(item.code ?? "").trim() || slugifyDesignationCode(String(item.label ?? ""));
      const label = String(item.label ?? item.code ?? "").trim();
      if (code && label && !seen.has(code)) {
        seen.add(code);
        out.push({ code, label });
      }
    }
  }
  return out.length > 0 ? out : DEFAULT_DESIGNATIONS.map((d) => ({ ...d }));
}

export function getDesignationLabel(
  designations: ReadonlyArray<DesignationOption>,
  codeOrLabel: string | null | undefined,
): string {
  const raw = String(codeOrLabel ?? "").trim();
  if (!raw) return "";
  const match = designations.find(
    (d) => d.code.toLowerCase() === raw.toLowerCase() || d.label.toLowerCase() === raw.toLowerCase(),
  );
  return match ? match.label : raw;
}

export function validateUserPin(
  pin: string | null | undefined,
): { valid: true } | { valid: false; error: string } {
  const cleaned = String(pin ?? "").trim();
  if (!/^[0-9]{6,16}$/.test(cleaned)) {
    return {
      valid: false,
      error: "PIN must be 6 to 16 digits (0-9).",
    };
  }
  return { valid: true };
}

export function daysUntilConfigExpiry(
  configExpiresAt: string | null | undefined,
  nowMs: number = Date.now(),
): number | null {
  if (!configExpiresAt || typeof configExpiresAt !== "string") return null;
  const targetMs = Date.parse(configExpiresAt);
  if (!Number.isFinite(targetMs)) return null;
  return Math.ceil((targetMs - nowMs) / (1000 * 60 * 60 * 24));
}

export function defaultStationRosterSnapshot(): StationRosterSnapshot {
  const now = new Date().toISOString();
  return {
    station_mode: "standalone",
    editable: true,
    station_config_id: null,
    config_expires_at: null,
    custodian: null,
    designations: DEFAULT_DESIGNATIONS.map((d) => ({ ...d })),
    members: [
      {
        user_id: null,
        member_id: "roster-mo-1",
        name: "Dr. Anil Sharma",
        designation: "medical_officer",
        is_reporter: true,
        is_interviewer: true,
        is_supervisor: true,
        is_coder: true,
        active: true,
        source: "sandbox",
        created_at: now,
        updated_at: now,
      },
      {
        user_id: null,
        member_id: "roster-hs-1",
        name: "Sunita Devi",
        designation: "health_supervisor",
        is_reporter: true,
        is_interviewer: true,
        is_supervisor: true,
        is_coder: false,
        active: true,
        source: "sandbox",
        created_at: now,
        updated_at: now,
      },
      {
        user_id: null,
        member_id: "roster-hw-1",
        name: "Rekha Kumari",
        designation: "health_worker",
        is_reporter: true,
        is_interviewer: true,
        is_supervisor: false,
        is_coder: false,
        active: true,
        source: "sandbox",
        created_at: now,
        updated_at: now,
      },
    ],
    active_actor: {
      user_id: null,
      member_id: "roster-mo-1",
      name: "Dr. Anil Sharma",
      designation: "medical_officer",
      acting_role: "station_supervisor",
      allowed_acting_roles: [
        "death_reporter",
        "interviewer",
        "station_supervisor",
        "coder",
      ],
    },
    recent_audit: [],
  };
}

function normaliseMember(
  raw: Record<string, unknown>,
  stationMode: "standalone" | "provisioned",
): StationRosterMember {
  const now = new Date().toISOString();
  const userId =
    typeof raw.user_id === "number" && Number.isInteger(raw.user_id)
      ? raw.user_id
      : null;
  const memberId =
    typeof raw.member_id === "string" && raw.member_id.trim()
      ? raw.member_id.trim()
      : userId !== null
        ? `user-${userId}`
        : `member-${Math.random().toString(36).slice(2, 9)}`;

  const rolesRaw = Array.isArray(raw.roles) ? raw.roles : undefined;
  const roles: StationRosterRoleScope[] | undefined = rolesRaw
    ? rolesRaw
        .filter((r): r is Record<string, unknown> => !!r && typeof r === "object")
        .map((r) => ({
          role: normaliseActingRole(String(r.role ?? "")),
          project_id: String(r.project_id ?? ""),
          site_id: String(r.site_id ?? ""),
          org_unit_id:
            typeof r.org_unit_id === "string" ? r.org_unit_id : null,
        }))
    : undefined;

  const hasRoleScope = (target: ActingRole) =>
    Boolean(roles?.some((r) => r.role === target));

  const isReporter =
    typeof raw.is_reporter === "boolean"
      ? raw.is_reporter
      : hasRoleScope("death_reporter");
  const isInterviewer =
    typeof raw.is_interviewer === "boolean"
      ? raw.is_interviewer
      : hasRoleScope("interviewer");
  const isSupervisor =
    typeof raw.is_supervisor === "boolean"
      ? raw.is_supervisor
      : hasRoleScope("station_supervisor");
  const isCoder =
    typeof raw.is_coder === "boolean" ? raw.is_coder : hasRoleScope("coder");

  return {
    user_id: userId,
    member_id: memberId,
    name: String(raw.name ?? ""),
    designation: String(raw.designation ?? "other"),
    ...(roles ? { roles } : {}),
    is_reporter: isReporter,
    is_interviewer: isInterviewer,
    is_supervisor: isSupervisor,
    is_coder: isCoder,
    active: raw.active !== false,
    source:
      raw.source === "provisioned" || stationMode === "provisioned"
        ? "provisioned"
        : "sandbox",
    created_at: typeof raw.created_at === "string" ? raw.created_at : now,
    updated_at: typeof raw.updated_at === "string" ? raw.updated_at : now,
  };
}

export function normaliseStationRosterSnapshot(
  raw: unknown,
): StationRosterSnapshot | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const obj = raw as Record<string, unknown>;
  const stationMode: "standalone" | "provisioned" =
    obj.station_mode === "provisioned" ? "provisioned" : "standalone";
  const editable =
    stationMode === "provisioned"
      ? false
      : typeof obj.editable === "boolean"
        ? obj.editable
        : true;
  const designations = normaliseDesignations(
    obj.designations as ReadonlyArray<string | DesignationOption> | undefined,
  );
  const rawMembers = Array.isArray(obj.members)
    ? obj.members
    : Array.isArray(obj.roster)
      ? obj.roster
      : null;
  if (!rawMembers) return null;

  const members = rawMembers
    .filter((m): m is Record<string, unknown> => !!m && typeof m === "object")
    .map((m) => normaliseMember(m, stationMode));

  if (stationMode === "provisioned") {
    members.sort((a, b) => (a.user_id ?? 0) - (b.user_id ?? 0));
  }

  let custodian: StationCustodian | null = null;
  if (obj.custodian && typeof obj.custodian === "object") {
    const c = obj.custodian as Record<string, unknown>;
    if (typeof c.name === "string" && c.name.trim()) {
      custodian = {
        name: c.name.trim(),
        designation: String(c.designation ?? ""),
        phone: typeof c.phone === "string" ? c.phone : null,
        email: typeof c.email === "string" ? c.email : null,
        onboarded_on: String(c.onboarded_on ?? ""),
        ...(typeof c.verified_by_user_id === "number"
          ? { verified_by_user_id: c.verified_by_user_id }
          : {}),
      };
    }
  }

  const actorRaw =
    obj.active_actor && typeof obj.active_actor === "object"
      ? (obj.active_actor as Record<string, unknown>)
      : null;
  const fallbackMember = members.find((m) => m.active) ?? members[0];
  const allowedRoles: ActingRole[] =
    actorRaw && Array.isArray(actorRaw.allowed_acting_roles)
      ? actorRaw.allowed_acting_roles.map((r) => normaliseActingRole(String(r)))
      : fallbackMember
        ? ([
            ...(fallbackMember.is_reporter ? (["death_reporter"] as const) : []),
            ...(fallbackMember.is_interviewer ? (["interviewer"] as const) : []),
            ...(fallbackMember.is_supervisor
              ? (["station_supervisor"] as const)
              : []),
            ...(fallbackMember.is_coder ? (["coder"] as const) : []),
          ] as ActingRole[])
        : ["interviewer"];

  const activeActor: ActiveActorContext = {
    user_id:
      actorRaw && typeof actorRaw.user_id === "number"
        ? actorRaw.user_id
        : (fallbackMember?.user_id ?? null),
    member_id:
      actorRaw && typeof actorRaw.member_id === "string"
        ? actorRaw.member_id
        : (fallbackMember?.member_id ?? "roster-mo-1"),
    name:
      actorRaw && typeof actorRaw.name === "string"
        ? actorRaw.name
        : (fallbackMember?.name ?? "Station Staff"),
    designation:
      actorRaw && typeof actorRaw.designation === "string"
        ? actorRaw.designation
        : (fallbackMember?.designation ?? "medical_officer"),
    acting_role: actorRaw
      ? normaliseActingRole(String(actorRaw.acting_role ?? ""))
      : (allowedRoles[0] ?? "interviewer"),
    allowed_acting_roles:
      allowedRoles.length > 0 ? allowedRoles : ["interviewer"],
  };

  return {
    station_mode: stationMode,
    editable,
    station_config_id:
      typeof obj.station_config_id === "string" ? obj.station_config_id : null,
    config_expires_at:
      typeof obj.config_expires_at === "string" ? obj.config_expires_at : null,
    custodian,
    designations,
    members,
    active_actor: activeActor,
    recent_audit: Array.isArray(obj.recent_audit)
      ? (obj.recent_audit as RosterAuditEntry[])
      : [],
    ...(Array.isArray(obj.purge)
      ? { purge: obj.purge.map((id) => String(id)) }
      : {}),
  };
}

export function formatActorAuditStamp(actor: ActiveActorContext): string {
  return `${actor.name} (${actor.designation}) [role:${actor.acting_role}]`;
}

export async function fetchStationRoster(
  csrf?: ClientCsrf,
): Promise<StationRosterSnapshot> {
  try {
    const res = await requestClientJson<unknown>("/api/v1/station/roster", {
      csrf,
    });
    const parsed = normaliseStationRosterSnapshot(res);
    if (parsed) {
      return parsed;
    }
  } catch {
    // Fallback when running against a server without the local station roster endpoint
  }
  return defaultStationRosterSnapshot();
}

export async function switchStationActingRole(
  memberId: string,
  actingRole: LegacyActingRole | undefined,
  csrf: ClientCsrf,
  pin?: string,
): Promise<{
  active_actor: ActiveActorContext;
  roster: StationRosterSnapshot;
  access?: unknown;
}> {
  const res = await requestClientJson<{
    active_actor: ActiveActorContext;
    roster: unknown;
    access?: unknown;
  }>("/api/v1/station/acting-role", {
    method: "POST",
    json: {
      member_id: memberId,
      ...(actingRole ? { acting_role: normaliseActingRole(actingRole) } : {}),
      ...(pin !== undefined && pin !== "" ? { pin } : {}),
    },
    csrf,
  });
  const normalisedRoster =
    normaliseStationRosterSnapshot(res.roster) ?? defaultStationRosterSnapshot();
  return {
    active_actor: normalisedRoster.active_actor,
    roster: normalisedRoster,
    access: res.access,
  };
}

export async function upsertStationRosterMember(
  input: UpsertRosterMemberInput,
  csrf: ClientCsrf,
): Promise<{ member: StationRosterMember; roster: StationRosterSnapshot }> {
  const res = await requestClientJson<{
    member: Record<string, unknown>;
    roster: unknown;
  }>("/api/v1/station/roster", {
    method: "POST",
    json: input,
    csrf,
  });
  const normalisedRoster =
    normaliseStationRosterSnapshot(res.roster) ?? defaultStationRosterSnapshot();
  return {
    member: normaliseMember(res.member ?? {}, normalisedRoster.station_mode),
    roster: normalisedRoster,
  };
}

export async function updateStationDesignations(
  designations: ReadonlyArray<string | DesignationOption>,
  csrf: ClientCsrf,
): Promise<{ designations: DesignationOption[]; roster: StationRosterSnapshot }> {
  const normalised = normaliseDesignations(designations);
  const res = await requestClientJson<{
    designations?: ReadonlyArray<string | DesignationOption>;
    roster: unknown;
  }>("/api/v1/station/designations", {
    method: "PUT",
    json: { designations: normalised },
    csrf,
  });
  const normalisedRoster =
    normaliseStationRosterSnapshot(res.roster) ?? defaultStationRosterSnapshot();
  return {
    designations: normalisedRoster.designations,
    roster: normalisedRoster,
  };
}

export interface StationConfigImportResult {
  station_config_id: string;
  station_mode: "provisioned";
  custodian: StationCustodian | null;
  config_expires_at?: string | null;
  purged_ids: string[];
  roster: StationRosterSnapshot;
}

export async function importStationConfig(
  rawStationConfig: string,
  csrf: ClientCsrf,
): Promise<StationConfigImportResult> {
  const res = await requestClientJson<{
    station_config_id?: string;
    custodian?: StationCustodian | null;
    config_expires_at?: string | null;
    purged_ids?: string[];
    roster?: unknown;
  }>("/api/v1/station/config", {
    method: "POST",
    json: { station_config: rawStationConfig },
    csrf,
  });
  const roster =
    normaliseStationRosterSnapshot(res.roster) ?? defaultStationRosterSnapshot();
  return {
    station_config_id: String(
      res.station_config_id ?? roster.station_config_id ?? "",
    ),
    station_mode: "provisioned",
    custodian: res.custodian ?? roster.custodian,
    config_expires_at: res.config_expires_at ?? roster.config_expires_at,
    purged_ids: Array.isArray(res.purged_ids)
      ? res.purged_ids.map((id) => String(id))
      : [],
    roster,
  };
}

export interface BundleExportResult {
  bundle_id: string;
  filename: string;
  record_count: number;
  bundle_bytes_b64?: string;
}

export async function exportStationBundle(
  csrf: ClientCsrf,
): Promise<BundleExportResult> {
  return requestClientJson<BundleExportResult>("/api/v1/station/bundles/export", {
    method: "POST",
    json: {},
    csrf,
  });
}

export interface BundleReceiptImportResult {
  bundle_id: string;
  acknowledged_deleted_count: number;
  purged_ids: string[];
}

export async function importBundleReceipt(
  rawReceipt: string,
  csrf: ClientCsrf,
): Promise<BundleReceiptImportResult> {
  const res = await requestClientJson<{
    bundle_id?: string;
    acknowledged_deleted_count?: number;
    purged_ids?: string[];
  }>("/api/v1/station/bundles/receipt", {
    method: "POST",
    json: { receipt: rawReceipt },
    csrf,
  });
  return {
    bundle_id: String(res.bundle_id ?? ""),
    acknowledged_deleted_count:
      typeof res.acknowledged_deleted_count === "number"
        ? res.acknowledged_deleted_count
        : 0,
    purged_ids: Array.isArray(res.purged_ids)
      ? res.purged_ids.map((id) => String(id))
      : [],
  };
}
