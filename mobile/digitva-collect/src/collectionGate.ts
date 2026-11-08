/**
 * The data-collection gate on the phone (docs/policy/project-clock-and-gates.md,
 * "Data-collection gate"; payload: docs/current-state/device-collection-api.md,
 * "Collection gate"). The server refuses a new start only for the browser; a phone
 * checks before a new registration or a new interview with no registration, from
 * the gate in its last /me/access answer plus its own starts since, and only when it
 * is online and that answer is under 15 minutes old ("The phone applies the gate only
 * online"); otherwise a new start is never blocked. Finishing, drafts and uploads are
 * never checked. No gate in the answer (older server) allows.
 */
import type { AccessSummary } from "./api";
import { getMeta, setMeta, type Db } from "./drafts";
import { t } from "./i18n";
import { isOffline } from "./network";
import { correctedNow } from "./phoneClock";

const KEY = "collection_gate";
const MAX_STARTS = 2000;
export const FRESH_MS = 15 * 60 * 1000;

export type GateReason = "collection_paused" | "collection_not_started" | "collection_ended" | "collection_daily_limit";

export interface GateEntry {
  site_id: string;
  org_unit_id?: string;
  enabled: boolean;
  start_date: string | null;
  end_date: string | null;
  daily_interviewer_limit: number | null;
  today_count: number;
  display_name: string;
}

interface ProjectGate {
  project_id: string;
  timezone?: string;
  project_today: string;
  server_time: string;
  sites: GateEntry[];
  units: GateEntry[];
}

interface Start { project_id: string; site_id: string; org_unit_id: string | null; day: string; at: number }

interface StoredGates { projects: ProjectGate[]; starts: Start[]; fetched_at?: number }

export type GateDecision =
  | { open: true }
  | { open: false; reason: GateReason; displayName: string; date: string | null; limit: number | null };

const DATE = /^\d{4}-\d{2}-\d{2}$/;
const isDate = (value: unknown): value is string => typeof value === "string" && DATE.test(value);
const dateOrNull = (value: unknown) => value === null || isDate(value);

function parseEntry(value: unknown, unit: boolean): GateEntry | undefined {
  if (!value || typeof value !== "object") return undefined;
  const e = value as Record<string, unknown>;
  const limit = e.daily_interviewer_limit;
  if (typeof e.site_id !== "string" || (unit && typeof e.org_unit_id !== "string") || typeof e.enabled !== "boolean" ||
      !dateOrNull(e.start_date) || !dateOrNull(e.end_date) || typeof e.display_name !== "string" ||
      !(limit === null || (Number.isInteger(limit) && (limit as number) >= 0)) ||
      !(Number.isInteger(e.today_count) && (e.today_count as number) >= 0)) return undefined;
  return {
    site_id: e.site_id, ...(unit ? { org_unit_id: e.org_unit_id as string } : {}), enabled: e.enabled,
    start_date: e.start_date as string | null, end_date: e.end_date as string | null,
    daily_interviewer_limit: limit as number | null, today_count: e.today_count as number, display_name: e.display_name,
  };
}

/** The gate parts of one validated /me/access answer; a project without a well-formed gate is left out (allowed). */
export function gatesFromAccess(access: AccessSummary): ProjectGate[] {
  const out: ProjectGate[] = [];
  for (const project of access.projects as unknown as Array<Record<string, unknown>>) {
    const gate = project.collection_gate as Record<string, unknown> | undefined;
    if (!gate || typeof gate !== "object" || !Array.isArray(gate.sites) || !Array.isArray(gate.units) ||
        !isDate(project.project_today) || typeof project.server_time !== "string" || !Number.isFinite(Date.parse(project.server_time))) continue;
    const sites = gate.sites.map((entry) => parseEntry(entry, false));
    const units = gate.units.map((entry) => parseEntry(entry, true));
    if (sites.some((entry) => !entry) || units.some((entry) => !entry)) continue;
    out.push({
      project_id: project.project_id as string,
      ...(typeof project.timezone === "string" ? { timezone: project.timezone } : {}),
      project_today: project.project_today, server_time: project.server_time,
      sites: sites as GateEntry[], units: units as GateEntry[],
    });
  }
  return out;
}

/** Today on the project clock: the server's date for that answer's day, else the phone's corrected clock in the project timezone. */
export function projectToday(project: Pick<ProjectGate, "timezone" | "project_today">, now: Date): string {
  if (!project.timezone) return project.project_today;
  try {
    const today = new Intl.DateTimeFormat("en-CA", { timeZone: project.timezone, year: "numeric", month: "2-digit", day: "2-digit" }).format(now);
    // An earlier date than the answer's means the phone clock is behind; trust the server's day.
    return isDate(today) && today >= project.project_today ? today : project.project_today;
  } catch {
    return project.project_today;
  }
}

/**
 * Pure gate check. `localStarts` are this phone's new starts for the same target on `today` since the
 * answer, added to the answer's `today_count`, which counts `answerDay` (the answer's project day,
 * default `today`) and is 0 on a later day. Dates are inclusive.
 */
export function evaluateGate(entry: GateEntry | undefined, today: string, localStarts: number, answerDay: string = today): GateDecision {
  if (!entry) return { open: true };
  const closed = (reason: GateReason, date: string | null = null, limit: number | null = null): GateDecision =>
    ({ open: false, reason, displayName: entry.display_name, date, limit });
  if (!entry.enabled) return closed("collection_paused");
  if (entry.start_date && today < entry.start_date) return closed("collection_not_started", entry.start_date);
  if (entry.end_date && today > entry.end_date) return closed("collection_ended", entry.end_date);
  const limit = entry.daily_interviewer_limit;
  if (limit !== null && (today === answerDay ? entry.today_count : 0) + localStarts >= limit) {
    return closed("collection_daily_limit", null, limit);
  }
  return { open: true };
}

/** The localised refusal, naming the site or unit and the date or limit. */
export function gateMessage(decision: Exclude<GateDecision, { open: true }>): string {
  const vars = { name: decision.displayName, date: decision.date ?? "", limit: decision.limit ?? "" };
  if (decision.reason === "collection_paused") return t("collectionPaused", vars);
  if (decision.reason === "collection_not_started") return t("collectionNotStarted", vars);
  if (decision.reason === "collection_ended") return t("collectionEnded", vars);
  return t("collectionDailyLimit", vars);
}

async function load(db: Db): Promise<StoredGates> {
  try {
    const stored = await getMeta<StoredGates>(db, KEY);
    if (stored && Array.isArray(stored.projects) && Array.isArray(stored.starts)) return stored;
  } catch {
    // Unreadable metadata is treated as no gate, as an older server is.
  }
  return { projects: [], starts: [] };
}

/** Keep the gate of a /me/access answer received at `receivedAt` (ms; a deferred answer passes its arrival time); starts older than every answer's server time stop counting. */
export async function rememberCollectionGate(db: Db, access: AccessSummary, receivedAt: number = Date.now()): Promise<void> {
  const { starts } = await load(db);
  const projects = gatesFromAccess(access);
  const kept = starts.filter((start) => {
    const project = projects.find((p) => p.project_id === start.project_id);
    return project && start.at > Date.parse(project.server_time);
  });
  await setMeta(db, KEY, { projects, starts: kept, fetched_at: receivedAt });
}

const sameTarget = (start: Start, projectId: string, siteId: string, orgUnitId: string | null) =>
  start.project_id === projectId && start.site_id === siteId && start.org_unit_id === orgUnitId;

/** Check the stored gate for one new start at a site, or a unit within it. */
export async function checkCollectionGate(db: Db, projectId: string, siteId: string, orgUnitId?: string | null): Promise<GateDecision> {
  if (isOffline()) return { open: true };
  const stored = await load(db);
  const age = Date.now() - (stored.fetched_at ?? -Infinity);
  if (!(age >= 0 && age <= FRESH_MS)) return { open: true };
  const project = stored.projects.find((p) => p.project_id === projectId);
  if (!project) return { open: true };
  const unit = orgUnitId ? project.units.find((e) => e.site_id === siteId && e.org_unit_id === orgUnitId) : undefined;
  const entry = unit ?? project.sites.find((e) => e.site_id === siteId);
  const today = projectToday(project, correctedNow());
  const since = Date.parse(project.server_time);
  const local = stored.starts.filter((s) => sameTarget(s, projectId, siteId, unit ? orgUnitId! : null) && s.day === today && s.at > since).length;
  return evaluateGate(entry, today, local, project.project_today);
}

/** Count one new start made on this phone, until the next /me/access answer covers it. */
export async function recordCollectionStart(db: Db, projectId: string, siteId: string, orgUnitId?: string | null): Promise<void> {
  const stored = await load(db);
  const project = stored.projects.find((p) => p.project_id === projectId);
  if (!project) return;
  const now = correctedNow();
  const unitGated = !!orgUnitId && project.units.some((e) => e.site_id === siteId && e.org_unit_id === orgUnitId);
  const starts = [...stored.starts, { project_id: projectId, site_id: siteId, org_unit_id: unitGated ? orgUnitId! : null, day: projectToday(project, now), at: now.getTime() }];
  await setMeta(db, KEY, { projects: stored.projects, starts: starts.slice(-MAX_STARTS), fetched_at: stored.fetched_at });
}
