/** Read-only account/project display. Saved metadata is never an authorization source. */
import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import { ApiError, parseAccessSummary, type AccessSummary } from "./api";
import { loadAccounts, loadActiveSlot, loadDevice, refreshAccessSummaryForAction, type Account, type Slot } from "./auth";
import { offlineCodingProjectIds } from "./codingCapabilities";
import { getMeta, setMeta, type Db } from "./drafts";
import { acceptedServerOrigin } from "./enrolment";
import { isUnlocked, openInterviewerDb } from "./interviewerDb";
import { getOfflineProfile, type OfflineProfile } from "./offlineProfile";
import { getCachedReferenceData, type ReferenceData } from "./sync";
import { t, type StringKey } from "./i18n";

const KEY = "accessProfile.v1";
const MAX_CHARACTERS = 256 * 1024;
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] =>
  Array.isArray(value) && value.length <= 1000 && value.every((entry) => typeof entry === "string" && entry.length <= 4000);

export interface AccessProfileProject {
  id: string;
  name: string;
  rights: string[];
  intake: string;
  codingMode: string;
  classification: string;
  selfCoding: string;
  localCoding: string;
  codingScope: string;
}

export interface AccessProfile {
  schema: 1;
  slot: Slot;
  server: string;
  userId: string;
  accessDigest: string;
  refreshedAt: string;
  name: string;
  roles: string[];
  codingLanguages: string[];
  projects: AccessProfileProject[];
}

export type LoadedAccessProfile =
  | { kind: "standalone"; userId: string; slot: Slot; name: string; profile: OfflineProfile | null }
  | { kind: "server"; current: boolean; profile: AccessProfile; reference?: ReferenceData };

/** The current unlocked account must still belong to this exact slot and server. */
export function profileAccountAvailable(account: Account | undefined): account is Account {
  return !!account && !account.signed_out && !account.needs_sign_in && !account.access_removed &&
    !account.access_blocked && !account.terms_required;
}

/** Labels retain unknown server roles without granting them any behavior. */
export function accessLabel(value: string): string {
  const labels: Record<string, string> = {
    project_pi: "Project principal investigator", site_pi: "In-charge", interviewer: "Interviewer",
    interview_supervisor: "Interview supervisor", death_reporter: "Death reporter", data_manager: "Data manager",
    coder: "Coder", coding_tester: "Coding tester", reviewer: "Reviewer", admin: "Administrator",
    unmasked_doris: "Unmasked with DORIS", direct: "Direct interview", death_register: "Death register",
    both: "Direct interview and death register", off: "Off", masked: "Masked",
  };
  return labels[value] ?? value.replace(/_/g, " ");
}

/** Translate app-created English display labels while leaving server names and unknown roles untouched. */
export function accessProfileDisplayText(value: string): string {
  const labels: Record<string, StringKey> = {
    "Project principal investigator": "profileRoleProjectPi",
    "In-charge": "profileRoleInCharge",
    Interviewer: "profileRoleInterviewer",
    "Interview supervisor": "profileRoleInterviewSupervisor",
    "Death reporter": "profileRoleDeathReporter",
    "Data manager": "profileRoleDataManager",
    Coder: "profileRoleCoder",
    "Coding tester": "profileRoleCodingTester",
    Reviewer: "profileRoleReviewer",
    Administrator: "profileRoleAdministrator",
    "Unmasked with DORIS": "profileUnmaskedDoris",
    "Direct interview": "profileDirectInterview",
    "Death register": "profileDeathRegister",
    "Direct interview and death register": "profileDirectInterviewAndDeathRegister",
    "Whole project": "profileWholeProject",
    "Assigned unit": "profileAssignedUnit",
    "Assigned site": "profileAssignedSite",
    "Coding allowed": "profileCodingAllowed",
    "Coding unavailable": "profileCodingUnavailable",
    "Self-coding": "profileSelfCoding",
    Inactive: "profileInactive",
    Off: "profileOff",
    Masked: "profileMasked",
    Enabled: "profileEnabled",
    Disabled: "profileDisabled",
    Eligible: "profileEligible",
    Unavailable: "profileUnavailable",
    "Not supplied by server": "profileNotSupplied",
    "Project scope": "profileProjectScope",
    Default: "profileDefault",
    "Under review": "profileUnderReview",
  };
  return value.split(" · ").map((part) => labels[part] ? t(labels[part]) : part).join(" · ");
}

/** Copy only display fields from a validated access answer; tokens and raw grants never reach metadata. */
export function projectAccessProfile(access: AccessSummary, scope: Pick<AccessProfile, "slot" | "server" | "userId" | "accessDigest">): AccessProfile {
  if (access.user.user_id !== scope.userId) throw new ApiError(200, "malformed_response");
  const eligible = offlineCodingProjectIds(access);
  const projects = access.projects.map((project): AccessProfileProject => {
    const mode = project.self_coding?.offline_coding;
    const scopeSetting = project.settings?.coding_scope;
    return {
      id: project.project_id, name: project.project_name,
      rights: project.grants.map((grant) => {
        const target = grant.scope === "project" ? "Whole project" : grant.scope === "org_unit"
          ? grant.unit_name || project.units?.find((unit) => unit.org_unit_id === grant.org_unit_id)?.unit_name || "Assigned unit"
          : project.sites.find((site) => site.site_id === grant.site_id)?.site_name ||
            [...project.actions.interview, ...project.actions.register_death].find((site) => site.site_id === grant.site_id)?.site_name || "Assigned site";
        const coding = grant.codes === undefined ? "" : grant.active && grant.codes ? " · Coding allowed" : " · Coding unavailable";
        return `${accessLabel(grant.role)} · ${target}${grant.active ? "" : " · Inactive"}${coding}${grant.source === "self_coding" ? " · Self-coding" : ""}`;
      }),
      intake: project.settings ? accessLabel(project.settings.web_intake_mode) : "Not supplied by server",
      codingMode: mode ? accessLabel(mode.project_mode) : "Not supplied by server",
      classification: mode?.icd_classification?.toUpperCase() ?? "Not supplied by server",
      selfCoding: project.self_coding ? (project.self_coding.enabled ? "Enabled" : "Disabled") : "Not supplied by server",
      localCoding: eligible.includes(project.project_id) ? "Eligible" : "Unavailable",
      codingScope: scopeSetting ? `${scopeSetting.level_code} · ${accessLabel(scopeSetting.above_mode)}` : project.settings ? "Whole project" : "Not supplied by server",
    };
  });
  return { schema: 1, ...scope, refreshedAt: new Date().toISOString(), name: access.user.name,
    roles: [...(access.is_admin ? ["Administrator"] : []), ...access.roles.map(accessLabel)],
    codingLanguages: access.user.coding_languages ?? [], projects };
}

/** Validate saved schema and identity before exposing any saved display field. */
export function parseSavedAccessProfile(value: unknown, scope: Pick<AccessProfile, "slot" | "server" | "userId" | "accessDigest">): AccessProfile | undefined {
  if (!record(value) || value.schema !== 1 || value.slot !== scope.slot || value.server !== scope.server ||
      value.userId !== scope.userId || value.accessDigest !== scope.accessDigest ||
      !/^[a-f0-9]{64}$/i.test(scope.accessDigest) || typeof value.name !== "string" ||
      typeof value.refreshedAt !== "string" || !Number.isFinite(Date.parse(value.refreshedAt)) ||
      !strings(value.roles) || !strings(value.codingLanguages) || !Array.isArray(value.projects) || value.projects.length > 1000) return undefined;
  for (const project of value.projects) {
    if (!record(project) || !["id", "name", "intake", "codingMode", "classification", "selfCoding", "localCoding", "codingScope"]
      .every((key) => typeof project[key] === "string" && (project[key] as string).length <= 4000) || !strings(project.rights)) return undefined;
  }
  if (JSON.stringify(value).length > MAX_CHARACTERS) return undefined;
  return value as unknown as AccessProfile;
}

/** Re-read persisted identity after async work, refusing a slot switch, logout, lock or server replacement. */
async function currentAccount(userId: string, slot: Slot, server?: string): Promise<Account> {
  if (await loadActiveSlot() !== slot || !isUnlocked(userId)) throw new Error("profile_access_unavailable");
  const account = (await loadAccounts(slot)).find((entry) => entry.user_id === userId);
  if (!profileAccountAvailable(account)) throw new Error("profile_access_unavailable");
  if (account.standalone) {
    if (server) throw new Error("profile_access_unavailable");
    return account;
  }
  const device = await loadDevice(slot);
  if (!server || !device || acceptedServerOrigin(device.server, __DEV__) !== server ||
      acceptedServerOrigin(account.server ?? "", __DEV__) !== server) throw new Error("profile_access_unavailable");
  return account;
}

/** Offline/network failures alone may show matching saved display metadata; refusals fail closed. */
export async function loadAccessProfile(userId: string, slot: Slot, server: string | undefined, offline: boolean): Promise<LoadedAccessProfile> {
  let account = await currentAccount(userId, slot, server);
  if (account.standalone) {
    const profile = await getOfflineProfile();
    await currentAccount(userId, slot);
    return { kind: "standalone", userId, slot, name: account.name, profile };
  }
  const db: Db = await openInterviewerDb(userId);
  let access: AccessSummary | undefined;
  if (!offline) {
    try {
      access = parseAccessSummary(await refreshAccessSummaryForAction(userId));
      if (access.user.user_id !== userId) throw new ApiError(200, "malformed_response");
    } catch (error) {
      if (!(error instanceof TypeError) && !(error instanceof Error && error.name === "AbortError")) {
        // Clear just this reconstructible metadata after any authentication, permission or schema refusal.
        await setMeta(db, KEY, null);
        throw error;
      }
    }
  }
  account = await currentAccount(userId, slot, server);
  if (!/^[a-f0-9]{64}$/i.test(account.coding_history_access ?? "")) throw new Error("profile_access_unavailable");
  const scope = { slot, server: server!, userId, accessDigest: account.coding_history_access! };
  let profile: AccessProfile | undefined;
  if (access) {
    const digest = await digestStringAsync(CryptoDigestAlgorithm.SHA256, JSON.stringify({ roles: access.roles, projects: access.projects }));
    if (digest !== scope.accessDigest) throw new Error("profile_access_unavailable");
    profile = projectAccessProfile(access, scope);
    if (!parseSavedAccessProfile(profile, scope)) {
      await setMeta(db, KEY, null);
      throw new ApiError(200, "malformed_response");
    }
    await setMeta(db, KEY, profile);
  } else {
    try {
      profile = parseSavedAccessProfile(await getMeta<unknown>(db, KEY), scope);
    } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  if (!profile) throw new Error("profile_access_unavailable");
  const cached = await getCachedReferenceData(db);
  const reference = cached?.bootstrap.user.user_id === userId ? cached : undefined;
  const latest = await currentAccount(userId, slot, server);
  if (latest.coding_history_access !== profile.accessDigest) throw new Error("profile_access_unavailable");
  return { kind: "server", current: !!access, profile, reference };
}

/** Read languages only from this account's compatible encrypted reference pack, never guessed defaults. */
export function profileQuestionnaireLanguages(projectId: string, reference?: ReferenceData): string | undefined {
  const project = reference?.projects.find((entry) => entry.project.project_id === projectId)?.project;
  const locales = project?.form_options.available_locales;
  if (!project || !locales?.length || !locales.every((locale) => record(locale) && typeof locale.code === "string" && typeof locale.label === "string")) return undefined;
  return locales.map((locale) => `${locale.label} (${locale.code})${locale.code === project.form_options.default_locale ? " · Default" : ""}${locale.under_review ? " · Under review" : ""}`).join(", ");
}
