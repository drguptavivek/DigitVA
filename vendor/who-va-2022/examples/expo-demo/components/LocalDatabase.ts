import * as SQLite from "expo-sqlite";

import { WHO_VA_FORM_VERSION, whoVa2022Instrument } from "@drguptavivek/who-2022-va";
import type { SubmissionData, SubmissionValidationResult, WhoVaDraft } from "@drguptavivek/who-2022-va";
import {
  clearSecureAuthValues,
  fetchWithAuth,
  loadAuthSession,
  loadStoredUserId,
  saveAuthSession,
  type AuthTokens
} from "./AuthSession";
import { clearDownloadedUserCaches } from "./UserFileCache";

export type UserRole = "admin" | "data-entry";

export interface RegisteredUser {
  userId: string;
  name: string;
  email: string;
  role: UserRole;
  partnerSite: string;
  siteAssigned: string;
  authKey: string;
  createdAt: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResult {
  user: RegisteredUser;
  tokens?: AuthTokens;
  fetchedServerRecords: number;
  importedServerRecords: number;
  syncWarning?: string;
  usedCachedUser?: boolean;
}

export interface ServerSyncResult {
  fetched: number;
  imported: number;
  skipped: number;
  errors: string[];
}

export interface CaseEntryData {
  district: string;
  block: string;
  villages: string;
  phc: string;
  subcentre: string;
  uid: string;
  date: string;
  householdHeadName: string;
  deceasedFullName: string;
  deceasedSex: "female" | "male" | "undetermined";
  deceasedHouseAddress: string;
  pinCode: string;
  deathDate: string;
  deathPlace: "hospital-death" | "home-death" | "on-the-way-to-hospital" | "other";
  ageAtDeath: number;
}

export interface StoredCaseEntry {
  uid: string;
  userId: string;
  caseEntry: CaseEntryData;
  whoVaData: SubmissionData;
  updatedAt: string;
}

export interface CompletedSubmission {
  id: string;
  completedAt: string;
  result: SubmissionValidationResult;
  syncStatus: "pending" | "pushed";
  authKey?: string;
  caseEntry?: CaseEntryData;
  userId?: string;
}

type Database = SQLite.SQLiteDatabase;

interface DraftRow {
  id: string;
  user_id?: string | null;
  created_at: string;
  updated_at: string;
  payload: string;
}

interface CompletedSubmissionRow {
  id: string;
  completed_at: string;
  payload: string;
  sync_status: "pending" | "pushed";
  auth_key?: string | null;
  case_entry?: string | null;
  user_id?: string | null;
}

interface UserRow {
  user_id: string;
  name: string;
  email: string;
  role: UserRole;
  partner_site: string;
  site_assigned: string;
  password_hash?: string;
  auth_key: string;
  created_at: string;
}

interface CaseEntryRow {
  uid: string;
  user_id: string;
  case_entry: string;
  who_va_data: string;
  updated_at: string;
}

interface ServerMobileSyncEntry {
  uid: string;
  userId?: string | null;
  status?: string;
  createdAt?: string;
  updatedAt?: string;
  completedAt?: string | null;
  caseEntry?: CaseEntryData | null;
  whoVaData?: SubmissionData | null;
  submission?: SubmissionData | null;
  validationIssues?: unknown[] | null;
}

let databasePromise: Promise<Database> | undefined;

async function openDatabase(): Promise<Database> {
  databasePromise ??= SQLite.openDatabaseAsync("who-va-2022.db");
  return databasePromise;
}

function decodeJson<T>(value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (error) {
    throw new Error(`Could not decode saved ${label}: ${(error as Error).message}`);
  }
}

async function addColumnIfMissing(
  database: Database,
  table: string,
  column: string,
  definition: string
): Promise<void> {
  const columns = await database.getAllAsync<{ name: string }>(`PRAGMA table_info(${table})`);
  if (columns.some((candidate) => candidate.name === column)) return;
  await database.execAsync(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`);
}

export async function initializeLocalDatabase(): Promise<void> {
  const database = await openDatabase();
  await database.execAsync(`
    PRAGMA journal_mode = WAL;

    CREATE TABLE IF NOT EXISTS drafts (
      id TEXT PRIMARY KEY NOT NULL,
      user_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      payload TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS completed_submissions (
      id TEXT PRIMARY KEY NOT NULL,
      completed_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      sync_status TEXT NOT NULL DEFAULT 'pending',
      user_id TEXT,
      auth_key TEXT,
      case_entry TEXT,
      pushed_at TEXT
    );

    CREATE TABLE IF NOT EXISTS users (
      user_id TEXT PRIMARY KEY NOT NULL,
      name TEXT NOT NULL,
      email TEXT NOT NULL UNIQUE,
      role TEXT NOT NULL,
      partner_site TEXT NOT NULL,
      site_assigned TEXT NOT NULL,
      password_hash TEXT NOT NULL,
      auth_key TEXT NOT NULL,
      created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS current_user (
      id INTEGER PRIMARY KEY CHECK (id = 1),
      user_id TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS case_entries (
      uid TEXT PRIMARY KEY NOT NULL,
      user_id TEXT NOT NULL,
      case_entry TEXT NOT NULL,
      who_va_data TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_drafts_updated_at
      ON drafts(updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_drafts_user_updated_at
      ON drafts(user_id, updated_at DESC);

    CREATE INDEX IF NOT EXISTS idx_completed_submissions_sync_status
      ON completed_submissions(sync_status, completed_at DESC);

    CREATE INDEX IF NOT EXISTS idx_case_entries_updated_at
      ON case_entries(updated_at DESC);
  `);
  await addColumnIfMissing(database, "completed_submissions", "user_id", "TEXT");
  await addColumnIfMissing(database, "completed_submissions", "auth_key", "TEXT");
  await addColumnIfMissing(database, "completed_submissions", "case_entry", "TEXT");
  await addColumnIfMissing(database, "drafts", "user_id", "TEXT");
}

function createLocalId(prefix: string): string {
  const random = Math.random().toString(36).slice(2, 10).toUpperCase();
  return `${prefix}-${Date.now().toString(36).toUpperCase()}-${random}`;
}

function userFromRow(row: UserRow): RegisteredUser {
  return {
    userId: row.user_id,
    name: row.name,
    email: row.email,
    role: row.role,
    partnerSite: row.partner_site,
    siteAssigned: row.site_assigned,
    authKey: row.auth_key,
    createdAt: row.created_at
  };
}

function hashPassword(password: string, email: string): string {
  let hash = 2166136261;
  const source = `${email.trim().toLowerCase()}:${password}`;
  for (let index = 0; index < source.length; index += 1) {
    hash ^= source.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return `local-fnv:${(hash >>> 0).toString(16)}`;
}

async function cacheServerUser(user: RegisteredUser, password: string): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    `
      INSERT INTO users (
        user_id, name, email, role, partner_site, site_assigned, password_hash, auth_key, created_at
      )
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(user_id) DO UPDATE SET
        name = excluded.name,
        email = excluded.email,
        role = excluded.role,
        partner_site = excluded.partner_site,
        site_assigned = excluded.site_assigned,
        password_hash = excluded.password_hash,
        auth_key = excluded.auth_key
    `,
    user.userId,
    user.name,
    user.email,
    user.role,
    user.partnerSite,
    user.siteAssigned,
    hashPassword(password, user.email),
    user.authKey,
    user.createdAt
  );
}

export async function loginCachedUser(data: LoginPayload): Promise<RegisteredUser> {
  const database = await openDatabase();
  const email = data.email.trim().toLowerCase();
  const row = await database.getFirstAsync<UserRow>(
    `
      SELECT user_id, name, email, role, partner_site, site_assigned, password_hash, auth_key, created_at
      FROM users
      WHERE lower(email) = ?
    `,
    email
  );

  if (!row?.auth_key || !row.password_hash || row.password_hash !== hashPassword(data.password, row.email)) {
    throw new Error("No matching local login found. First login must be online.");
  }

  await setCurrentUser(row.user_id);
  return userFromRow(row);
}

export async function listUsers(): Promise<RegisteredUser[]> {
  const database = await openDatabase();
  const rows = await database.getAllAsync<UserRow>(
    `
      SELECT user_id, name, email, role, partner_site, site_assigned, password_hash, auth_key, created_at
      FROM users
      ORDER BY name ASC, email ASC
    `
  );
  return rows.map(userFromRow);
}

function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return trimmed;
  const withProtocol = /^https?:\/\//iu.test(trimmed) ? trimmed : `http://${trimmed}`;
  try {
    const url = new URL(withProtocol);
    url.pathname = url.pathname.replace(/\/api(?:\/.*)?$/u, "");
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/$/u, "");
  } catch {
    return withProtocol.replace(/\/api(?:\/.*)?$/u, "");
  }
}

function nonJsonApiResponseMessage(url: string, status: number): string {
  return `The server at ${url} returned a web page instead of API data (HTTP ${status}). Use the WHO VA API server URL, for example http://YOUR-COMPUTER-IP:5173, and make sure the demo server is running.`;
}
function createMobileSyncUrl(apiBaseUrl: string): string {
  return `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}/api/mobile-sync`;
}

function createHealthUrl(apiBaseUrl: string): string {
  return `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}/api/health`;
}

function createSyncedSubmissionResult(entry: ServerMobileSyncEntry): SubmissionValidationResult {
  return {
    data: entry.submission ?? {},
    formVersion: WHO_VA_FORM_VERSION,
    instrumentId: whoVa2022Instrument.id,
    instrumentVersion: whoVa2022Instrument.version,
    issues: Array.isArray(entry.validationIssues) ? entry.validationIssues : [],
    valid: !Array.isArray(entry.validationIssues) || entry.validationIssues.length === 0
  } as SubmissionValidationResult;
}

function normalizeServerDeathPlace(value: unknown): CaseEntryData["deathPlace"] | undefined {
  if (typeof value !== "string") return undefined;
  const normalized = value.trim().toLowerCase().replace(/[_-]+/gu, " ").replace(/\s+/gu, " ");
  if (["hospital death", "hospital", "health facility", "facility"].includes(normalized)) {
    return "hospital-death";
  }
  if (["home death", "home"].includes(normalized)) return "home-death";
  if (["on the way to hospital", "on way to hospital", "transit"].includes(normalized)) {
    return "on-the-way-to-hospital";
  }
  if (["other", "other place", "others"].includes(normalized)) return "other";
  return undefined;
}

function normalizeServerCaseEntry(
  entry: CaseEntryData,
  whoVaData: SubmissionData | null | undefined
): CaseEntryData {
  return {
    ...entry,
    householdHeadName: entry.householdHeadName?.trim() || "Not Recorded",
    deathPlace:
      normalizeServerDeathPlace(entry.deathPlace) ??
      normalizeServerDeathPlace(whoVaData?.Id10058) ??
      "other"
  };
}

async function importServerEntries(
  user: RegisteredUser,
  entries: ServerMobileSyncEntry[]
): Promise<Omit<ServerSyncResult, "fetched">> {
  const result: Omit<ServerSyncResult, "fetched"> = { imported: 0, skipped: 0, errors: [] };
  const existingCasesByUid = new Map((await listCaseEntries(user.userId)).map((entry) => [entry.uid, entry]));
  const existingCompletedByCaseUid = new Map<string, CompletedSubmission>();
  for (const submission of await listCompletedSubmissions(user.userId)) {
    const caseUid = submission.result.data.__caseUid;
    const uid = typeof caseUid === "string" ? caseUid : submission.caseEntry?.uid;
    if (!uid) continue;
    const previous = existingCompletedByCaseUid.get(uid);
    if (!previous || new Date(submission.completedAt).getTime() > new Date(previous.completedAt).getTime()) {
      existingCompletedByCaseUid.set(uid, submission);
    }
  }

  for (const entry of entries) {
    if (!entry.uid || !entry.caseEntry) {
      result.skipped += 1;
      continue;
    }
    const caseEntry = normalizeServerCaseEntry(entry.caseEntry, entry.whoVaData ?? entry.submission);
    const validationError = validateCaseEntryData(caseEntry);
    if (validationError) {
      result.skipped += 1;
      result.errors.push(`${entry.uid}: ${validationError}`);
      continue;
    }
    const updatedAt = entry.updatedAt ?? entry.completedAt ?? entry.createdAt ?? new Date().toISOString();
    const existingCase = existingCasesByUid.get(entry.uid);
    const entryUserId = entry.userId ?? user.userId;
    if (
      existingCase?.userId === entryUserId &&
      new Date(existingCase.updatedAt).getTime() > new Date(updatedAt).getTime()
    ) {
      result.skipped += 1;
      continue;
    }
    try {
      await saveCaseEntry({
        uid: entry.uid,
        userId: entryUserId,
        caseEntry,
        whoVaData: entry.whoVaData ?? {},
        updatedAt
      });
      result.imported += 1;
    } catch (error) {
      result.skipped += 1;
      result.errors.push(`${entry.uid}: ${(error as Error).message}`);
      continue;
    }

    if (entry.status === "completed" && entry.submission) {
      const completedAt = entry.completedAt ?? updatedAt;
      const existingCompleted = existingCompletedByCaseUid.get(entry.uid);
      if (
        existingCompleted &&
        new Date(existingCompleted.completedAt).getTime() > new Date(completedAt).getTime()
      ) {
        continue;
      }
      try {
        await saveCompletedSubmission({
          id: `server-${entry.uid}`,
          completedAt,
          result: createSyncedSubmissionResult(entry),
          syncStatus: "pushed",
          userId: entryUserId,
          authKey: user.authKey,
          caseEntry
        });
      } catch (error) {
        result.errors.push(`${entry.uid}: completed submission was not imported: ${(error as Error).message}`);
      }
    }
  }
  return result;
}

export async function syncServerDataForUser(
  user: RegisteredUser,
  apiBaseUrl: string
): Promise<ServerSyncResult> {
  const healthUrl = createHealthUrl(apiBaseUrl);
  const url = createMobileSyncUrl(apiBaseUrl);
  let response: Response;
  try {
    const healthResponse = await fetch(healthUrl);
    if (!healthResponse.ok) {
      throw new Error(`health check returned HTTP ${healthResponse.status}`);
    }
    response = await fetchWithAuth(apiBaseUrl, "/api/mobile-sync", {
      headers: {
        "x-user-id": user.userId,
        "x-auth-key": user.authKey
      }
    });
  } catch (error) {
    throw new Error(
      `Could not reach server records API at ${url}. Health check: ${healthUrl}. ${(error as Error).message}`
    );
  }
  const responseText = await response.text();
  let body: { ok: boolean; entries?: ServerMobileSyncEntry[]; error?: string };
  try {
    body = responseText
      ? (JSON.parse(responseText) as { ok: boolean; entries?: ServerMobileSyncEntry[]; error?: string })
      : { ok: false };
  } catch {
    throw new Error(nonJsonApiResponseMessage(url, response.status));
  }
  if (!response.ok || !body.ok) throw new Error(body.error ?? "Could not sync server records.");
  const entries = body.entries ?? [];
  return { fetched: entries.length, ...(await importServerEntries(user, entries)) };
}

export async function loginOnlineUser(data: LoginPayload, apiBaseUrl: string): Promise<LoginResult> {
  const url = `${normalizeApiBaseUrl(apiBaseUrl).replace(/\/$/u, "")}/api/login`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(data)
    });
  } catch (_error) {
    try {
      const cachedUser = await loginCachedUser(data);
      return {
        user: cachedUser,
        fetchedServerRecords: 0,
        importedServerRecords: 0,
        syncWarning:
          "Signed in offline from cached login. Server records were not checked because the API could not be reached.",
        usedCachedUser: true
      };
    } catch (localError) {
      throw new Error(
        `Could not reach login server at ${url}. ${(localError as Error).message} Check server, IP address, Wi-Fi, and firewall.`
      );
    }
  }

  const responseText = await response.text();
  let body: {
    ok: boolean;
    user?: RegisteredUser;
    accessToken?: string;
    refreshToken?: string;
    entries?: ServerMobileSyncEntry[];
    error?: string;
  };
  try {
    body = responseText
      ? (JSON.parse(responseText) as {
          ok: boolean;
          user?: RegisteredUser;
          accessToken?: string;
          refreshToken?: string;
          entries?: ServerMobileSyncEntry[];
          error?: string;
        })
      : { ok: false };
  } catch {
    throw new Error(nonJsonApiResponseMessage(url, response.status));
  }
  if (!response.ok || !body.ok || !body.user?.authKey) {
    throw new Error(body.error ?? "Online login failed.");
  }
  if (!body.accessToken || !body.refreshToken) {
    throw new Error("Online login did not return access and refresh tokens.");
  }
  await saveAuthSession({
    accessToken: body.accessToken,
    refreshToken: body.refreshToken,
    user: body.user,
    apiBaseUrl
  });
  await cacheServerUser(body.user, data.password);
  const serverEntries = body.entries ?? [];
  const importResult = await importServerEntries(body.user, serverEntries);
  await setCurrentUser(body.user.userId);
  return {
    user: body.user,
    tokens: { accessToken: body.accessToken, refreshToken: body.refreshToken },
    fetchedServerRecords: serverEntries.length,
    importedServerRecords: importResult.imported,
    syncWarning: importResult.errors[0]
      ? `Signed in as ${body.user.name}. Found ${serverEntries.length} server records; imported ${importResult.imported}; skipped ${importResult.skipped}. ${importResult.errors[0]}`
      : undefined
  };
}
export async function setCurrentUser(userId: string): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    "INSERT INTO current_user (id, user_id) VALUES (1, ?) ON CONFLICT(id) DO UPDATE SET user_id = excluded.user_id",
    userId
  );
}

export async function loadCurrentUser(): Promise<RegisteredUser | undefined> {
  const session = await loadAuthSession();
  if (session?.user) return session.user;
  const database = await openDatabase();
  const row = await database.getFirstAsync<UserRow>(
    `
      SELECT users.user_id, name, email, role, partner_site, site_assigned, auth_key, created_at
      FROM current_user
      JOIN users ON users.user_id = current_user.user_id
      WHERE current_user.id = 1
    `
  );
  return row ? userFromRow(row) : undefined;
}

export async function logoutCurrentUser(): Promise<void> {
  const database = await openDatabase();
  await database.runAsync("DELETE FROM current_user WHERE id = 1");
}

export async function clearUserSession(userId?: string): Promise<void> {
  const resolvedUserId = userId ?? (await loadStoredUserId());
  const database = await openDatabase();
  if (resolvedUserId) {
    await database.runAsync("DELETE FROM drafts WHERE user_id = ? OR user_id IS NULL", resolvedUserId);
    await database.runAsync(
      "DELETE FROM completed_submissions WHERE user_id = ? OR user_id IS NULL",
      resolvedUserId
    );
    await database.runAsync("DELETE FROM case_entries WHERE user_id = ?", resolvedUserId);
    await database.runAsync("DELETE FROM current_user WHERE id = 1");
    await database.runAsync("DELETE FROM users WHERE user_id = ?", resolvedUserId);
  } else {
    await database.runAsync("DELETE FROM drafts WHERE user_id IS NULL");
    await database.runAsync("DELETE FROM completed_submissions WHERE user_id IS NULL");
    await database.runAsync("DELETE FROM current_user WHERE id = 1");
  }
  await clearDownloadedUserCaches();
  await clearSecureAuthValues();
}

export async function listDrafts(userId?: string): Promise<WhoVaDraft[]> {
  if (!userId) return [];
  const database = await openDatabase();
  const rows = await database.getAllAsync<DraftRow>(
    "SELECT id, user_id, created_at, updated_at, payload FROM drafts WHERE user_id = ? ORDER BY updated_at DESC",
    userId
  );
  return rows.map((row) => decodeJson<WhoVaDraft>(row.payload, `draft ${row.id}`));
}

export async function loadDraft(id: string, userId?: string): Promise<WhoVaDraft | undefined> {
  if (!userId) return undefined;
  const database = await openDatabase();
  const row = await database.getFirstAsync<DraftRow>(
    "SELECT id, user_id, created_at, updated_at, payload FROM drafts WHERE id = ? AND user_id = ?",
    id,
    userId
  );
  return row ? decodeJson<WhoVaDraft>(row.payload, `draft ${row.id}`) : undefined;
}

export async function saveDraft(draft: WhoVaDraft, userId?: string): Promise<void> {
  if (!userId) throw new Error("Login before saving drafts.");
  const database = await openDatabase();
  await database.runAsync(
    `
      INSERT INTO drafts (id, user_id, created_at, updated_at, payload)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        user_id = excluded.user_id,
        updated_at = excluded.updated_at,
        payload = excluded.payload
    `,
    draft.id,
    userId,
    draft.createdAt,
    draft.updatedAt,
    JSON.stringify(draft)
  );
}

export async function removeDraft(id: string): Promise<void> {
  const database = await openDatabase();
  await database.runAsync("DELETE FROM drafts WHERE id = ?", id);
}

export async function listCompletedSubmissions(userId?: string): Promise<CompletedSubmission[]> {
  if (!userId) return [];
  const database = await openDatabase();
  const rows = await database.getAllAsync<CompletedSubmissionRow>(
    `
      SELECT id, completed_at, payload, sync_status, user_id, auth_key, case_entry
      FROM completed_submissions
      WHERE user_id = ?
      ORDER BY completed_at DESC
    `,
    userId
  );
  return rows.flatMap((row) => {
    try {
      return [
        {
          id: row.id,
          completedAt: row.completed_at,
          result: decodeJson<SubmissionValidationResult>(row.payload, `completed submission ${row.id}`),
          syncStatus: row.sync_status,
          ...(row.user_id ? { userId: row.user_id } : {}),
          ...(row.auth_key ? { authKey: row.auth_key } : {}),
          ...(row.case_entry
            ? { caseEntry: decodeJson<CaseEntryData>(row.case_entry, `case entry ${row.id}`) }
            : {})
        }
      ];
    } catch {
      return [];
    }
  });
}

export async function saveCompletedSubmission(submission: CompletedSubmission): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    `
      INSERT INTO completed_submissions (id, completed_at, payload, sync_status, user_id, auth_key, case_entry)
      VALUES (?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(id) DO UPDATE SET
        completed_at = excluded.completed_at,
        payload = excluded.payload,
        sync_status = excluded.sync_status,
        user_id = excluded.user_id,
        auth_key = excluded.auth_key,
        case_entry = excluded.case_entry
    `,
    submission.id,
    submission.completedAt,
    JSON.stringify(submission.result),
    submission.syncStatus,
    submission.userId ?? null,
    submission.authKey ?? null,
    submission.caseEntry ? JSON.stringify(submission.caseEntry) : null
  );
}

export async function markCompletedSubmissionPushed(id: string): Promise<void> {
  const database = await openDatabase();
  await database.runAsync(
    "UPDATE completed_submissions SET sync_status = 'pushed', pushed_at = ? WHERE id = ?",
    new Date().toISOString(),
    id
  );
}

export function createEntryUid(): string {
  return createLocalId("VA");
}

function isFutureDate(value: string): boolean {
  const date = new Date(`${value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return !Number.isNaN(date.getTime()) && date.getTime() > today.getTime();
}

export function validateCaseEntryData(caseEntry: CaseEntryData): string | undefined {
  const characterOnlyFields: Array<[keyof CaseEntryData, string]> = [
    ["district", "District"],
    ["block", "Block"],
    ["villages", "Villages"],
    ["phc", "Phc"],
    ["subcentre", "Subcentre"],
    ["householdHeadName", "Name of head of the Household"],
    ["deceasedFullName", "Full name of the deceased"]
  ];
  for (const [field, label] of characterOnlyFields) {
    const value = String(caseEntry[field] ?? "").trim();
    if (!/^[A-Za-z]+(?: [A-Za-z]+)*$/u.test(value)) {
      return `${label} accepts letters only. Spaces are allowed between words.`;
    }
  }
  if (!["female", "male", "undetermined"].includes(caseEntry.deceasedSex)) {
    return "Select a valid sex of the deceased.";
  }
  if (!caseEntry.uid.trim()) return "UID is required.";
  if (!caseEntry.date) return "Entry date is required.";
  if (!caseEntry.deceasedHouseAddress.trim()) return "House address of the deceased is required.";
  if (!/^[0-9]{6}$/u.test(caseEntry.pinCode.trim())) return "Pin code must be exactly 6 digits.";
  if (!caseEntry.deathDate) return "Death date is required.";
  if (isFutureDate(caseEntry.deathDate)) return "Death date cannot be in the future.";
  if (!["hospital-death", "home-death", "on-the-way-to-hospital", "other"].includes(caseEntry.deathPlace)) {
    return "Select a valid death place.";
  }
  if (!Number.isInteger(caseEntry.ageAtDeath) || caseEntry.ageAtDeath < 0 || caseEntry.ageAtDeath > 130) {
    return "Age at the time of death must be a whole number from 0 to 130.";
  }
  return undefined;
}

export async function saveCaseEntry(entry: StoredCaseEntry): Promise<void> {
  const validationError = validateCaseEntryData(entry.caseEntry);
  if (validationError) throw new Error(validationError);
  const database = await openDatabase();
  await database.runAsync(
    `
      INSERT INTO case_entries (uid, user_id, case_entry, who_va_data, updated_at)
      VALUES (?, ?, ?, ?, ?)
      ON CONFLICT(uid) DO UPDATE SET
        user_id = excluded.user_id,
        case_entry = excluded.case_entry,
        who_va_data = excluded.who_va_data,
        updated_at = excluded.updated_at
    `,
    entry.uid,
    entry.userId,
    JSON.stringify(entry.caseEntry),
    JSON.stringify(entry.whoVaData),
    entry.updatedAt
  );
}

export async function listCaseEntries(userId?: string): Promise<StoredCaseEntry[]> {
  if (!userId) return [];
  const database = await openDatabase();
  const rows = await database.getAllAsync<CaseEntryRow>(
    "SELECT uid, user_id, case_entry, who_va_data, updated_at FROM case_entries WHERE user_id = ? ORDER BY updated_at DESC",
    userId
  );
  return rows.flatMap((row) => {
    try {
      return [
        {
          uid: row.uid,
          userId: row.user_id,
          caseEntry: decodeJson<CaseEntryData>(row.case_entry, `case entry ${row.uid}`),
          whoVaData: decodeJson<SubmissionData>(row.who_va_data, `WHO VA prefill ${row.uid}`),
          updatedAt: row.updated_at
        }
      ];
    } catch {
      return [];
    }
  });
}

export async function loadCaseEntry(uid: string, userId?: string): Promise<StoredCaseEntry | undefined> {
  return (await listCaseEntries(userId)).find((entry) => entry.uid === uid);
}
