/**
 * Adoption and push of a standalone (Path C) store after the phone enrols (docs/policy/field-data-collection.md
 * "Path C", offline contract section 17).
 *
 * The records stay in the standalone account's own encrypted store, which acts as a separate push queue: once the
 * user confirms adoption (on the standalone home, behind the standalone PIN) the store remembers the enrolled
 * account, project and site, and each push sends its completed interviews with that account's bearer
 * (src/sync.ts uploadQueuedWork with `standalone`). Nothing moves between stores and nothing is deleted before the
 * server acknowledges it; an acknowledged interview leaves with its offline coding and consent record.
 */
import type { Account, Device } from "../auth";
import { loadDevice } from "../auth";
import type { AccessSummary } from "../api";
import { completedDrafts, getMeta, setMeta, type Db, type OfflineCodingRow } from "../drafts";
import { loadConsents } from "../consentStore";
import { t } from "../i18n";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { getOfflineProfile, type OfflineProfile } from "../offlineProfile";
import { isCodingStale, isUploadable, offlineCodingBody, sentAnswers, uploadQueuedWork, type StandalonePush, type UploadResult } from "../sync";

const ADOPTION_KEY = "standalone:adoption";
const NOTICES_KEY = "standalone:coding_notices";
const MAX_NOTICES = 50;
/** The server's org_code pattern, a unit code at any tree level (offline_coding_import_service._ORG_CODE): anything else is sent as null. */
const ORG_CODE = /^[A-Za-z0-9_-]{1,64}$/;
const SNAPSHOT_MAX = 200;

/** The enrolled account, project and site a standalone store's records go to; fixed once the user confirms. */
export interface StandaloneAdoption {
  userId: string;
  userName: string;
  server: string;
  projectId: string;
  siteId: string;
  siteName: string;
  adoptedAt: string;
}

export const getAdoption = async (db: Db) => (await getMeta<StandaloneAdoption>(db, ADOPTION_KEY)) ?? null;
export const saveAdoption = (db: Db, adoption: StandaloneAdoption) => setMeta(db, ADOPTION_KEY, adoption);

/** What adoption would send, as the offer lists it. */
export interface StandaloneCounts {
  /** Completed interviews the push will send. */
  interviews: number;
  /** Coding results that go with them. */
  codings: number;
  /** Coded interviews whose answers changed after coding: the interview is sent, its coding is not. */
  staleDraftIds: string[];
  /** Interviews held after a refusal (shown on the home, sent again only on request). */
  held: number;
}

/** Counts for the offer; codings are judged by the same rule the push applies (offlineCodingBody). */
export async function standaloneCounts(db: Db, clientDeviceUuid: string): Promise<StandaloneCounts> {
  // ponytail: reads every completed envelope to hash it; a standalone pilot phone holds hundreds at most.
  const [items, consents, codingRows, heldRow] = await Promise.all([
    completedDrafts(db),
    loadConsents(db),
    db.getAllAsync<OfflineCodingRow>("SELECT * FROM offline_coding", []),
    db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM drafts WHERE upload_issue IS NOT NULL", []),
  ]);
  const coding = new Map(codingRows.map((row) => [row.client_draft_id, row]));
  const counts: StandaloneCounts = { interviews: 0, codings: 0, staleDraftIds: [], held: Number(heldRow?.n ?? 0) };
  for (const item of items) {
    if (!isUploadable(item.draft.data, item.completion)) continue;
    counts.interviews += 1;
    const row = coding.get(item.id);
    if (!row) continue;
    const { answersHash } = await sentAnswers(item, consents);
    if (offlineCodingBody(row, answersHash, clientDeviceUuid)) counts.codings += 1;
    else if (row.status === "coded" && isCodingStale(row, answersHash)) counts.staleDraftIds.push(item.id);
  }
  return counts;
}

/** Enrolled accounts the records may be adopted into: signed in, collecting, not gated. */
export const adoptionTargets = (accounts: readonly Account[]) => accounts.filter((account) =>
  !account.standalone && !account.needs_sign_in && !account.access_removed && !account.terms_required &&
  !account.access_blocked && account.collection_access !== false);

/**
 * The "Send your standalone records to <server>?" offer: only on an enrolled phone whose standalone store holds
 * interviews to send, not yet adopted, with at least one enrolled account to send them as.
 */
export function adoptionOffer(input: {
  device: Device | undefined;
  accounts: readonly Account[];
  counts: StandaloneCounts | undefined;
  adoption: StandaloneAdoption | null | undefined;
}): { host: string; targets: Account[] } | null {
  const { device, counts } = input;
  if (!device || !counts || counts.interviews === 0 || input.adoption) return null;
  const targets = adoptionTargets(input.accounts);
  return targets.length ? { host: new URL(device.server).host, targets } : null;
}

/** A site the enrolled account may start interviews at directly (standalone interviews have no death record). */
export interface AdoptionSite {
  projectId: string;
  siteId: string;
  siteName: string;
}

export function adoptionSites(access: AccessSummary): AdoptionSite[] {
  return access.projects.flatMap((project) => project.actions.interview
    .filter((context) => context.web_intake_mode === "direct" || context.web_intake_mode === "both")
    .map((context) => ({ projectId: project.project_id, siteId: context.site_id, siteName: `${project.project_name} · ${context.site_name}` })));
}

/** The profile's org code as the server will take it, or null (never a guess from the facility name). */
export function orgCodeClaim(code: string | null | undefined): string | null {
  const trimmed = (code ?? "").trim();
  return ORG_CODE.test(trimmed) ? trimmed : null;
}

const snapshotText = (value: string | null | undefined) => (value ?? "").trim().slice(0, SNAPSHOT_MAX) || null;

/** The contract 17 profile_snapshot: four texts of at most 200 characters, blanks as null. */
export function profileSnapshot(profile: OfflineProfile | null): StandalonePush["profileSnapshot"] {
  return {
    name: snapshotText(profile?.name),
    designation: snapshotText(profile?.designation),
    facility: snapshotText(profile?.facility_name),
    country: snapshotText(profile?.country),
  };
}

/** A coding the server did not use (or the phone did not send because it was stale), for the user to read. */
export interface CodingNotice {
  draftId: string;
  code: string;
  at: string;
}

export const codingNotices = async (db: Db) => (await getMeta<CodingNotice[]>(db, NOTICES_KEY)) ?? [];
export const dismissCodingNotices = (db: Db) => db.runAsync("DELETE FROM meta WHERE key = ?", [NOTICES_KEY]);

async function addCodingNotices(db: Db, notices: CodingNotice[]): Promise<void> {
  if (!notices.length) return;
  await setMeta(db, NOTICES_KEY, [...notices, ...(await codingNotices(db))].slice(0, MAX_NOTICES));
}

/**
 * Send the adopted store's completed interviews (with their offline coding) as the adopted account. Throws
 * `standalone_not_adopted` before adoption and `standalone_server_changed` when the phone is now enrolled with
 * another server; network and session failures propagate with every record kept.
 */
export async function pushStandaloneRecords(db: Db): Promise<UploadResult> {
  const adoption = await getAdoption(db);
  if (!adoption) throw new Error("standalone_not_adopted");
  const device = await loadDevice();
  if (!device || device.server !== adoption.server) throw new Error("standalone_server_changed");
  const identity = await getOrCreatePlusDeviceIdentity();
  if (!identity) throw new Error("standalone_plus_only");
  const profile = await getOfflineProfile();
  const result = await uploadQueuedWork(adoption.userId, db, {
    standalone: {
      projectId: adoption.projectId,
      siteId: adoption.siteId,
      clientDeviceUuid: identity.uuid,
      profileSnapshot: profileSnapshot(profile),
      orgCode: orgCodeClaim(profile?.org_code),
    },
  });
  const at = new Date().toISOString();
  await addCodingNotices(db, [
    ...(result.codingOutcomes ?? []).filter((outcome) => outcome.status === "refused")
      .map((outcome) => ({ draftId: outcome.draftId, code: outcome.code ?? "not_available", at })),
    // Not sent: the server would have refused it the same way (coded_version_superseded).
    ...(result.staleCodingDraftIds ?? []).map((draftId) => ({ draftId, code: "coded_version_superseded", at })),
  ]);
  return result;
}

/** Plain text for a coding the server refused (contract 17 reply codes); an allocation code reads generically. */
export function codingNoticeText(code: string): string {
  switch (code) {
    case "coding_grant_required": return t("standaloneCodingRefusedGrant");
    case "coding_mode_mismatch": return t("standaloneCodingRefusedMode");
    case "coded_version_superseded": return t("standaloneCodingRefusedStale");
    case "not_available": return t("standaloneCodingRefusedNotAvailable");
    default: return t("standaloneCodingRefusedAllocation", { code });
  }
}

/** Plain text for an interview held after a refusal (contract 17 and the section 8 catalogue). */
export function heldText(code: string | null | undefined): string {
  switch (code) {
    case "device_mismatch": return t("standaloneHeldDeviceMismatch");
    case "conflict": return t("standaloneHeldConflict");
    case "consent_invalid":
    case "consent_required":
    case "consent_conflict": return t("standaloneHeldConsent");
    case "standalone_invalid":
    case "offline_coding_invalid": return t("standaloneHeldInvalid", { code });
    default: return t("standaloneHeldOther", { code: code ?? "-" });
  }
}
