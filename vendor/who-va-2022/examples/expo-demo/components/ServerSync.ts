import type { SubmissionData, WhoVaDraft } from "@drguptavivek/who-2022-va";

import {
  markCompletedSubmissionPushed,
  type CaseEntryData,
  type CompletedSubmission,
  type RegisteredUser,
  type StoredCaseEntry
} from "./LocalDatabase";
import { fetchWithAuth } from "./AuthSession";

interface SaveFormEntryPayload {
  uid: string;
  userId: string;
  authKey: string;
  caseEntry: CaseEntryData;
  whoVaData: SubmissionData;
  status: "completed";
  submission?: SubmissionData;
  validationIssues?: unknown[];
}

export interface PushResult {
  pushed: number;
  skipped: number;
  failed: number;
  errors: string[];
}

function nonJsonApiResponseMessage(status: number): string {
  return `Server returned a web page instead of API data while pushing data (HTTP ${status}). Use the WHO VA API server URL, not the Expo app URL.`;
}

async function readJsonResponse<T extends { error?: string }>(response: Response): Promise<T> {
  const responseText = await response.text();
  try {
    return responseText ? (JSON.parse(responseText) as T) : ({} as T);
  } catch {
    throw new Error(nonJsonApiResponseMessage(response.status));
  }
}

async function pushFormEntry(apiBaseUrl: string, payload: SaveFormEntryPayload): Promise<void> {
  const response = await fetchWithAuth(apiBaseUrl, "/api/form-entries", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-user-id": payload.userId,
      "x-auth-key": payload.authKey
    },
    body: JSON.stringify(payload)
  });
  const body = await readJsonResponse<{ ok: boolean; error?: string }>(response);
  if (!response.ok || !body.ok) {
    throw new Error(body.error ?? `Push failed for ${payload.uid}. Status: ${response.status}.`);
  }
}

function caseUidFromCompleted(submission: CompletedSubmission): string | undefined {
  const caseUid = submission.result.data.__caseUid;
  return typeof caseUid === "string" ? caseUid : submission.caseEntry?.uid;
}

function buildCompletedPayload(
  user: RegisteredUser,
  caseEntry: CaseEntryData,
  uid: string,
  whoVaData: SubmissionData,
  submission: CompletedSubmission,
  draft?: WhoVaDraft
): SaveFormEntryPayload {
  return {
    uid,
    userId: user.userId,
    authKey: user.authKey,
    caseEntry,
    whoVaData: draft?.data ?? whoVaData,
    status: "completed",
    submission: submission.result.data,
    validationIssues: submission.result.issues
  };
}

export async function pushLocalDataToServer({
  apiBaseUrl,
  cases,
  completed,
  currentUser,
  drafts,
  submissionIds
}: {
  apiBaseUrl: string;
  cases: StoredCaseEntry[];
  completed: CompletedSubmission[];
  currentUser: RegisteredUser | undefined;
  drafts: WhoVaDraft[];
  submissionIds?: string[];
}): Promise<PushResult> {
  if (!currentUser?.userId || !currentUser.authKey) {
    throw new Error("Login with an online user before pushing mobile data.");
  }

  const result: PushResult = { pushed: 0, skipped: 0, failed: 0, errors: [] };
  const casesByUid = new Map(cases.map((entry) => [entry.uid, entry]));
  const draftsById = new Map(drafts.map((draft) => [draft.id, draft]));
  const allowedSubmissionIds = submissionIds ? new Set(submissionIds) : undefined;

  for (const submission of completed) {
    if (allowedSubmissionIds && !allowedSubmissionIds.has(submission.id)) continue;
    if (submission.syncStatus === "pushed") {
      result.skipped += 1;
      continue;
    }
    const uid = caseUidFromCompleted(submission);
    const storedCase = uid ? casesByUid.get(uid) : undefined;
    const caseEntry = storedCase?.caseEntry ?? submission.caseEntry;
    const submissionUserId = submission.userId ?? storedCase?.userId;
    if (
      !uid ||
      !caseEntry ||
      (submissionUserId && submissionUserId !== currentUser.userId) ||
      !submission.result.valid
    ) {
      result.skipped += 1;
      continue;
    }
    try {
      await pushFormEntry(
        apiBaseUrl,
        buildCompletedPayload(
          currentUser,
          caseEntry,
          uid,
          storedCase?.whoVaData ?? submission.result.data,
          submission,
          draftsById.get(uid)
        )
      );
      await markCompletedSubmissionPushed(submission.id);
      result.pushed += 1;
    } catch (error) {
      result.failed += 1;
      result.errors.push((error as Error).message);
    }
  }

  return result;
}
