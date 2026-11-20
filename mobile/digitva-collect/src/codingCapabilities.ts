import type { AccessSummary } from "./api";
import type { Account } from "./auth";

/** Server-authoritative projects where this account may use local coding tools. */
export function offlineCodingProjectIds(access: AccessSummary): string[] {
  return access.projects
    .filter((project) => project.self_coding?.enabled === true &&
      project.self_coding.offline_coding?.enabled === true &&
      project.self_coding.offline_coding.project_mode === "unmasked_doris" &&
      project.self_coding.offline_coding.icd_classification === "icd11" &&
      project.grants.some((grant) =>
      grant.active && grant.codes === true && grant.role === "coder"))
    .map((project) => project.project_id);
}

/** What the project asks with an offline final (digitva-p8uj), by project id; older servers send neither (false). */
export type OfflineCodingQuality = Record<string, { narrative_qa: boolean; social_autopsy: boolean }>;

export function offlineCodingQuality(access: AccessSummary): OfflineCodingQuality {
  const quality: OfflineCodingQuality = {};
  const offlineProjects = new Set(offlineCodingProjectIds(access));
  for (const project of access.projects) {
    if (!offlineProjects.has(project.project_id)) continue;
    const offline = project.self_coding?.offline_coding;
    if (offline?.narrative_qa_enabled === true || offline?.social_autopsy_enabled === true) {
      quality[project.project_id] = { narrative_qa: offline.narrative_qa_enabled === true, social_autopsy: offline.social_autopsy_enabled === true };
    }
  }
  return quality;
}

/** Cached local capability. Missing/invalid cached access stays unavailable until /me/access refreshes. */
export function canUseOfflineCoding(account: Pick<Account, "standalone" | "offline_coding_access" | "needs_sign_in" | "access_removed" | "access_blocked" | "terms_required" | "signed_out">, projectId?: string): boolean {
  if (account.needs_sign_in || account.access_removed || account.access_blocked || account.terms_required || account.signed_out) return false;
  if (account.standalone === true) return true;
  const projects = account.offline_coding_access;
  return Array.isArray(projects) && projects.length > 0 && (projectId === undefined || projects.includes(projectId));
}

export function canUseOnlineCoding(account: Pick<Account, "coding_access">): boolean {
  return account.coding_access === true;
}
