/**
 * The interviewer's own answers (Id10010 name, Id10010a age, Id10010b sex,
 * Id10010c ID) recalled from their last interview into a new one
 * (docs/policy/digitva-who-form-overrides.md, "Interviewer's own details
 * recalled"). Only these four are ever kept; the respondent's data never is.
 * The phone stores the value in the signed-in user's encrypted meta table;
 * the browser in localStorage keyed by user id.
 */
import type { SubmissionData } from "@drguptavivek/who-2022-va";

export const RECALL_NAMES = ["Id10010", "Id10010a", "Id10010b", "Id10010c"] as const;
export const RECALL_META_KEY = "interviewer_recall";
const WEB_KEY = "digitva.interviewerRecall.";

export type InterviewerRecall = Partial<Record<(typeof RECALL_NAMES)[number], string | number>>;

const filled = (value: unknown): value is string | number =>
  (typeof value === "string" && value.trim() !== "") || (typeof value === "number" && Number.isFinite(value));

/** The four answers present in a draft's data, or undefined when none is. */
export function recallFromData(data: SubmissionData | undefined): InterviewerRecall | undefined {
  const recall: InterviewerRecall = {};
  for (const name of RECALL_NAMES) {
    const value = data?.[name];
    if (filled(value)) recall[name] = value;
  }
  return Object.keys(recall).length ? recall : undefined;
}

/** True when saving *next* would change what is stored as *stored*. */
export const recallChanged = (stored: InterviewerRecall | undefined, next: InterviewerRecall | undefined): boolean =>
  JSON.stringify(stored ?? null) !== JSON.stringify(next ?? null);

/**
 * Initial answers with the recalled ones in the empty slots; with no recall,
 * the account's display name for Id10010. Never overwrites an answer.
 */
export function withInterviewerRecall(
  data: SubmissionData | undefined,
  recall: InterviewerRecall | undefined,
  accountName?: string,
): SubmissionData {
  const out: SubmissionData = { ...(data ?? {}) };
  const source: InterviewerRecall = recall ?? (accountName?.trim() ? { Id10010: accountName.trim() } : {});
  for (const name of RECALL_NAMES) {
    const value = source[name];
    if (!filled(out[name]) && filled(value)) out[name] = value;
  }
  return out;
}

export function readWebRecall(userId: string): InterviewerRecall | undefined {
  try {
    const raw = globalThis.localStorage?.getItem(WEB_KEY + userId);
    return raw ? (JSON.parse(raw) as InterviewerRecall) : undefined;
  } catch {
    return undefined;
  }
}

export function writeWebRecall(userId: string, recall: InterviewerRecall | undefined): void {
  try {
    if (recall) globalThis.localStorage?.setItem(WEB_KEY + userId, JSON.stringify(recall));
  } catch {
    // storage blocked: the recall is a convenience
  }
}
