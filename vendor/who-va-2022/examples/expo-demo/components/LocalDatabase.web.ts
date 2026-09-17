import type { SubmissionValidationResult, WhoVaDraft } from "@drguptavivek/who-2022-va";

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

export interface CompletedSubmission {
  id: string;
  completedAt: string;
  result: SubmissionValidationResult;
  syncStatus: "pending" | "pushed";
  authKey?: string;
  caseEntry?: CaseEntryData;
  userId?: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResult {
  user: RegisteredUser;
  tokens?: { accessToken: string; refreshToken: string };
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
  whoVaData: Record<string, unknown>;
  updatedAt: string;
}

const DRAFTS_KEY = "who-va-2022:expo-demo:drafts";
const COMPLETED_KEY = "who-va-2022:expo-demo:completed";
const USERS_KEY = "who-va-2022:expo-demo:users";
const CASES_KEY = "who-va-2022:expo-demo:cases";

function readJson<T>(key: string, fallback: T): T {
  const value = globalThis.localStorage?.getItem(key);
  return value ? (JSON.parse(value) as T) : fallback;
}

function writeJson<T>(key: string, value: T): void {
  globalThis.localStorage?.setItem(key, JSON.stringify(value));
}

export async function initializeLocalDatabase(): Promise<void> {
  readJson<WhoVaDraft[]>(DRAFTS_KEY, []);
  readJson<CompletedSubmission[]>(COMPLETED_KEY, []);
  readJson<RegisteredUser[]>(USERS_KEY, []);
  readJson<StoredCaseEntry[]>(CASES_KEY, []);
}

export async function listDrafts(_userId?: string): Promise<WhoVaDraft[]> {
  return readJson<WhoVaDraft[]>(DRAFTS_KEY, []).sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  );
}

export async function loadDraft(id: string, _userId?: string): Promise<WhoVaDraft | undefined> {
  return (await listDrafts()).find((draft) => draft.id === id);
}

export async function saveDraft(draft: WhoVaDraft, _userId?: string): Promise<void> {
  const drafts = (await listDrafts()).filter((savedDraft) => savedDraft.id !== draft.id);
  writeJson(DRAFTS_KEY, [draft, ...drafts]);
}

export async function removeDraft(id: string): Promise<void> {
  writeJson(
    DRAFTS_KEY,
    (await listDrafts()).filter((draft) => draft.id !== id)
  );
}

export async function listCompletedSubmissions(_userId?: string): Promise<CompletedSubmission[]> {
  return readJson<CompletedSubmission[]>(COMPLETED_KEY, []).sort(
    (left, right) => new Date(right.completedAt).getTime() - new Date(left.completedAt).getTime()
  );
}

export async function saveCompletedSubmission(submission: CompletedSubmission): Promise<void> {
  const submissions = (await listCompletedSubmissions()).filter((saved) => saved.id !== submission.id);
  writeJson(COMPLETED_KEY, [submission, ...submissions]);
}

export async function markCompletedSubmissionPushed(id: string): Promise<void> {
  writeJson(
    COMPLETED_KEY,
    (await listCompletedSubmissions()).map((submission) =>
      submission.id === id ? { ...submission, syncStatus: "pushed" } : submission
    )
  );
}

export async function listUsers(): Promise<RegisteredUser[]> {
  return readJson<RegisteredUser[]>(USERS_KEY, []).sort((left, right) => left.name.localeCompare(right.name));
}

export async function listCaseEntries(_userId?: string): Promise<StoredCaseEntry[]> {
  return readJson<StoredCaseEntry[]>(CASES_KEY, []).sort(
    (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
  );
}

export async function loginOnlineUser(_data: LoginPayload, _apiBaseUrl: string): Promise<LoginResult> {
  throw new Error("Online login is not available in the web storage demo.");
}

export async function syncServerDataForUser(
  _user: RegisteredUser,
  _apiBaseUrl: string
): Promise<ServerSyncResult> {
  return { fetched: 0, imported: 0, skipped: 0, errors: [] };
}

export async function loadCurrentUser(): Promise<RegisteredUser | undefined> {
  return undefined;
}

export async function logoutCurrentUser(): Promise<void> {
  return undefined;
}

export async function clearUserSession(_userId?: string): Promise<void> {
  return undefined;
}

export async function saveCaseEntry(entry: StoredCaseEntry): Promise<void> {
  const cases = (await listCaseEntries()).filter((saved) => saved.uid !== entry.uid);
  writeJson(CASES_KEY, [entry, ...cases]);
}

export function createEntryUid(): string {
  return `VA-${Date.now().toString(36).toUpperCase()}-${Math.random().toString(36).slice(2, 10).toUpperCase()}`;
}

function isFutureDate(value: string): boolean {
  const date = new Date(`${value}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return !Number.isNaN(date.getTime()) && date.getTime() > today.getTime();
}

export function validateCaseEntryData(caseEntry: CaseEntryData): string | undefined {
  if (!caseEntry.deathDate) return "Death date is required.";
  if (isFutureDate(caseEntry.deathDate)) return "Death date cannot be in the future.";
  return undefined;
}
