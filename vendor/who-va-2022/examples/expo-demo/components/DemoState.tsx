import Constants from "expo-constants";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { createWhoVaInitialDataFromPrefill } from "@drguptavivek/who-2022-va";
import type {
  SubmissionData,
  SubmissionValidationResult,
  WhoVaDraft,
  WhoVaDraftStore
} from "@drguptavivek/who-2022-va";

import {
  clearUserSession,
  createEntryUid,
  initializeLocalDatabase,
  listCaseEntries,
  listCompletedSubmissions,
  listDrafts,
  listUsers,
  loadCurrentUser,
  loadDraft,
  loginOnlineUser,
  logoutCurrentUser,
  removeDraft,
  saveCaseEntry,
  saveCompletedSubmission,
  saveDraft,
  syncServerDataForUser,
  validateCaseEntryData,
  type CaseEntryData,
  type CompletedSubmission,
  type LoginPayload,
  type RegisteredUser,
  type ServerSyncResult,
  type StoredCaseEntry
} from "./LocalDatabase";
import { revokeRefreshToken, SessionExpiredError } from "./AuthSession";
import { pushLocalDataToServer, type PushResult } from "./ServerSync";
export type { CaseEntryData, CompletedSubmission, RegisteredUser, StoredCaseEntry } from "./LocalDatabase";

interface DemoState {
  completed: CompletedSubmission[];
  cases: StoredCaseEntry[];
  currentUser: RegisteredUser | undefined;
  draftStore: WhoVaDraftStore;
  drafts: WhoVaDraft[];
  isDatabaseReady: boolean;
  latestDraft: WhoVaDraft | undefined;
  lastUpdate: string;
  newFormKey: number;
  users: RegisteredUser[];
  defaultApiBaseUrl: string;
  addCompleted(result: SubmissionValidationResult, caseEntry?: CaseEntryData): void;
  beginNewInterview(): void;
  getDraft(id: string | undefined): WhoVaDraft | undefined;
  login(payload: LoginPayload, apiBaseUrl?: string): Promise<void>;
  logout(): Promise<void>;
  switchUser(apiBaseUrl?: string): Promise<void>;
  pushToServer(apiBaseUrl?: string, submissionIds?: string[]): Promise<PushResult>;
  syncFromServer(apiBaseUrl?: string): Promise<ServerSyncResult>;
  saveCase(caseEntry: CaseEntryData): Promise<StoredCaseEntry>;
  setLastUpdate(message: string): void;
}

function apiBaseUrlFromExpoHost(): string | undefined {
  const hostUri = Constants.expoConfig?.hostUri ?? Constants.manifest2?.extra?.expoClient?.hostUri;
  const host = typeof hostUri === "string" ? hostUri.split(":")[0] : undefined;
  return host ? `http://${host}:5173` : undefined;
}

const API_BASE_URL =
  process.env.EXPO_PUBLIC_WHO_VA_API_URL ?? apiBaseUrlFromExpoHost() ?? "http://127.0.0.1:5173";

const DemoStateContext = createContext<DemoState | undefined>(undefined);

function syncUserLabel(user: RegisteredUser): string {
  return `${user.email} (${user.userId})`;
}

export function countAnswers(draft: WhoVaDraft): number {
  return Object.values(draft.data).filter((value) => value !== undefined && value !== null && value !== "")
    .length;
}

export function formatDateTime(value: string): string {
  return new Date(value).toLocaleString();
}

export function DemoStateProvider({ children }: { children: ReactNode }) {
  const [isDatabaseReady, setIsDatabaseReady] = useState(false);
  const [lastUpdate, setLastUpdate] = useState("Opening local database");
  const [drafts, setDrafts] = useState<WhoVaDraft[]>([]);
  const [completed, setCompleted] = useState<CompletedSubmission[]>([]);
  const [cases, setCases] = useState<StoredCaseEntry[]>([]);
  const [currentUser, setCurrentUser] = useState<RegisteredUser | undefined>(undefined);
  const [newFormKey, setNewFormKey] = useState(0);
  const [users, setUsers] = useState<RegisteredUser[]>([]);
  const [serverApiBaseUrl, setServerApiBaseUrl] = useState(API_BASE_URL);

  const resetUserState = useCallback(() => {
    setDrafts([]);
    setCompleted([]);
    setCases([]);
    setCurrentUser(undefined);
    setNewFormKey((current) => current + 1);
  }, []);

  const refreshLocalData = useCallback(async (userId?: string) => {
    const [savedDrafts, savedCompleted, savedCases, savedUsers] = await Promise.all([
      listDrafts(userId),
      listCompletedSubmissions(userId),
      listCaseEntries(userId),
      listUsers()
    ]);
    setDrafts(savedDrafts);
    setCompleted(savedCompleted);
    setCases(savedCases);
    setUsers(savedUsers);
  }, []);

  useEffect(() => {
    let isMounted = true;

    void initializeLocalDatabase()
      .then(async () => {
        const savedUser = await loadCurrentUser();
        if (isMounted) setCurrentUser(savedUser);
        await refreshLocalData(savedUser?.userId);
      })
      .then(() => {
        if (!isMounted) return;
        setIsDatabaseReady(true);
        setLastUpdate("Local SQLite storage ready");
      })
      .catch((error: unknown) => {
        if (!isMounted) return;
        setLastUpdate(`Local database failed: ${(error as Error).message}`);
      });

    return () => {
      isMounted = false;
    };
  }, [refreshLocalData]);

  const draftStore = useMemo<WhoVaDraftStore>(() => {
    return {
      async save(draft) {
        if (!currentUser) throw new Error("Login before saving drafts.");
        setDrafts((current) =>
          [draft, ...current.filter((savedDraft) => savedDraft.id !== draft.id)].sort(
            (left, right) => new Date(right.updatedAt).getTime() - new Date(left.updatedAt).getTime()
          )
        );
        await saveDraft(draft, currentUser.userId);
        await refreshLocalData(currentUser.userId);
      },
      async load(id) {
        return loadDraft(id, currentUser?.userId);
      },
      async remove(id) {
        await removeDraft(id);
        await refreshLocalData(currentUser?.userId);
      }
    };
  }, [currentUser, refreshLocalData]);

  const value = useMemo<DemoState>(
    () => ({
      addCompleted(result, caseEntry) {
        setLastUpdate(`Submission ready with ${Object.keys(result.data).length} answers`);
        const resultCaseUid = result.data.__caseUid;
        const matchingCase = cases.find(
          (entry) => entry.uid === resultCaseUid || entry.uid === caseEntry?.uid
        );
        const resolvedCaseEntry = matchingCase?.caseEntry ?? caseEntry;
        const submission: CompletedSubmission = {
          completedAt: new Date().toISOString(),
          id: `completed-${Date.now()}`,
          result,
          syncStatus: "pending",
          userId: currentUser?.userId ?? matchingCase?.userId,
          authKey: currentUser?.authKey,
          caseEntry: resolvedCaseEntry
        };
        setCompleted((current) => [submission, ...current]);
        void saveCompletedSubmission(submission)
          .then(() => refreshLocalData(currentUser?.userId))
          .catch((error: unknown) => {
            setLastUpdate(`Local submission save failed: ${(error as Error).message}`);
          });
        console.log("validated submission saved locally", result);
      },
      beginNewInterview() {
        setNewFormKey((current) => current + 1);
        setLastUpdate("New interview started");
      },
      completed,
      cases,
      currentUser,
      draftStore,
      drafts,
      defaultApiBaseUrl: API_BASE_URL,
      getDraft(id) {
        if (!id) return undefined;
        return drafts.find((draft) => draft.id === id);
      },
      isDatabaseReady,
      async login(payload, apiBaseUrl) {
        const targetApiBaseUrl = apiBaseUrl?.trim() || API_BASE_URL;
        if (currentUser) {
          await revokeRefreshToken(serverApiBaseUrl);
          await clearUserSession(currentUser.userId);
          resetUserState();
        }
        const loginResult = await loginOnlineUser(payload, targetApiBaseUrl);
        const { fetchedServerRecords, importedServerRecords, syncWarning, user } = loginResult;
        setServerApiBaseUrl(targetApiBaseUrl);
        setCurrentUser(user);
        setLastUpdate(
          syncWarning ??
            `Signed in as ${user.name}${
              fetchedServerRecords
                ? `. Found ${fetchedServerRecords} server records; imported ${importedServerRecords}.`
                : `. No server records found for ${syncUserLabel(user)}.`
            }`
        );
        await refreshLocalData(user.userId);
      },
      async logout() {
        await revokeRefreshToken(serverApiBaseUrl);
        await clearUserSession(currentUser?.userId);
        await logoutCurrentUser();
        resetUserState();
        setLastUpdate("Signed out");
      },
      async switchUser(apiBaseUrl) {
        await revokeRefreshToken(apiBaseUrl?.trim() || serverApiBaseUrl);
        await clearUserSession(currentUser?.userId);
        await logoutCurrentUser();
        resetUserState();
        setLastUpdate("Signed out. Login with the next account.");
      },
      async pushToServer(apiBaseUrl, submissionIds) {
        let result: PushResult;
        try {
          result = await pushLocalDataToServer({
            apiBaseUrl: apiBaseUrl?.trim() || serverApiBaseUrl,
            cases,
            completed,
            currentUser,
            drafts,
            submissionIds
          });
        } catch (error) {
          if (error instanceof SessionExpiredError) {
            await clearUserSession(currentUser?.userId);
            resetUserState();
            setLastUpdate(error.message);
          }
          throw error;
        }
        await refreshLocalData(currentUser?.userId);
        const messageParts = [`Pushed ${result.pushed} entries`];
        if (result.skipped) messageParts.push(`${result.skipped} skipped`);
        if (result.failed) messageParts.push(`${result.failed} failed`);
        setLastUpdate(messageParts.join(", "));
        return result;
      },
      async syncFromServer(apiBaseUrl) {
        if (!currentUser) throw new Error("Login before syncing server data.");
        const targetApiBaseUrl = apiBaseUrl?.trim() || serverApiBaseUrl;
        setServerApiBaseUrl(targetApiBaseUrl);
        let result: ServerSyncResult;
        try {
          result = await syncServerDataForUser(currentUser, targetApiBaseUrl);
        } catch (error) {
          if (error instanceof SessionExpiredError) {
            await clearUserSession(currentUser.userId);
            resetUserState();
            setLastUpdate(error.message);
          }
          throw error;
        }
        await refreshLocalData(currentUser.userId);
        setLastUpdate(
          result.fetched
            ? `Found ${result.fetched} server records; imported ${result.imported}; skipped ${result.skipped}.${
                result.errors[0] ? ` ${result.errors[0]}` : ""
              }`
            : `No server records found for ${syncUserLabel(currentUser)}.`
        );
        return result;
      },
      latestDraft: drafts[0],
      lastUpdate,
      newFormKey,
      users,
      async saveCase(caseEntry) {
        if (!currentUser) throw new Error("Login before saving case data.");
        const validationError = validateCaseEntryData(caseEntry);
        if (validationError) throw new Error(validationError);
        const whoVaData = createWhoVaDataFromCaseEntry(caseEntry);
        const stored: StoredCaseEntry = {
          uid: caseEntry.uid,
          userId: currentUser.userId,
          caseEntry,
          whoVaData,
          updatedAt: new Date().toISOString()
        };
        await saveCaseEntry(stored);
        await refreshLocalData(currentUser.userId);
        setLastUpdate(`Case saved: ${caseEntry.deceasedFullName}`);
        return stored;
      },
      setLastUpdate
    }),
    [
      cases,
      completed,
      currentUser,
      draftStore,
      drafts,
      isDatabaseReady,
      lastUpdate,
      newFormKey,
      refreshLocalData,
      resetUserState,
      serverApiBaseUrl,
      users
    ]
  );

  return <DemoStateContext.Provider value={value}>{children}</DemoStateContext.Provider>;
}

export function emptyCaseEntry(): CaseEntryData {
  return {
    district: "",
    block: "",
    villages: "",
    phc: "",
    subcentre: "",
    uid: createEntryUid(),
    date: new Date().toISOString().slice(0, 10),
    householdHeadName: "",
    deceasedFullName: "",
    deceasedSex: "undetermined",
    deceasedHouseAddress: "",
    pinCode: "",
    deathDate: "",
    deathPlace: "home-death",
    ageAtDeath: 0
  };
}

export function createWhoVaDataFromCaseEntry(entry: CaseEntryData): SubmissionData {
  const deceased =
    entry.ageAtDeath >= 12
      ? {
          givenNames: entry.deceasedFullName,
          sex: entry.deceasedSex,
          ageInYears: entry.ageAtDeath,
          dateOfDeath: entry.deathDate
        }
      : {
          givenNames: entry.deceasedFullName,
          sex: entry.deceasedSex,
          dateOfDeath: entry.deathDate
        };
  const whoVaData = createWhoVaInitialDataFromPrefill({
    deceased,
    location: {
      district: entry.district,
      village: entry.villages
    }
  });

  if (entry.ageAtDeath > 0 && entry.ageAtDeath < 12) {
    whoVaData.Id10020 = "no";
    whoVaData.age_group = "child";
    whoVaData.age_child_unit = "years";
    whoVaData.age_child_years = entry.ageAtDeath;
  }

  whoVaData.__caseUid = entry.uid;
  return whoVaData;
}

export function useDemoState(): DemoState {
  const state = useContext(DemoStateContext);
  if (!state) throw new Error("useDemoState must be used inside DemoStateProvider");
  return state;
}
