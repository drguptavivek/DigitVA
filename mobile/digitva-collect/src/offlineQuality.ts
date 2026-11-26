/**
 * Narrative Quality Assessment for enrolled offline coding (digitva-p8uj): the project asks it of the offline final
 * as the web and online coding do (docs/policy/doris-cod-workflow.md, "Offline coding workspace"). Saved in the
 * account's encrypted store beside the draft, bound to the answers it was assessed on, and sent inside the final's
 * `offline_coding` object (contract 17). The bundled display pack shows the social autopsy answers read-only offline;
 * the coder's Social Autopsy analysis is still not asked offline.
 */
import type { Db } from "./drafts";
import { getMeta, setMeta } from "./drafts";
import type { NarrativeQuality, NarrativeSaved } from "./workspace/contracts";

/** The server's NARRATIVE_QA_FIELDS (app/services/narrative_qa_service.py); keep the two in step. */
export const NARRATIVE_QA_FIELDS: NarrativeQuality["fields"] = [
  { key: "length", label: "Q1. Length of Narrative", options: [{ value: 1, label: "< 3 sentences" }, { value: 2, label: "3–5 sentences" }, { value: 3, label: "> 5 sentences" }] },
  { key: "pos_symptoms", label: "Q2. Number of Positive Symptoms", options: [{ value: 1, label: "< 3 symptoms" }, { value: 2, label: "3–5 symptoms" }, { value: 3, label: "> 5 symptoms" }] },
  { key: "neg_symptoms", label: "Q3. Presence of Negative Symptoms", options: [{ value: 0, label: "Absent" }, { value: 1, label: "Present" }] },
  { key: "chronology", label: "Q4. Chronology of Events", options: [{ value: 0, label: "Cannot be established" }, { value: 1, label: "Can be established" }] },
  { key: "doc_review", label: "Q5. Document Review", options: [{ value: 0, label: "Not present / Inconclusive" }, { value: 1, label: "Provides useful data" }] },
  { key: "comorbidity", label: "Q6. Comorbidities / Risk Factors", options: [{ value: 0, label: "Not present" }, { value: 1, label: "Present" }] },
];
export const NARRATIVE_QA_MAX_SCORE = NARRATIVE_QA_FIELDS.reduce((sum, field) => sum + Math.max(...field.options.map((option) => option.value)), 0);

/** The wire answers: `cannot_grade` and each field's score point (zeros when it cannot be graded, as online). */
export type NarrativeAnswers = { cannot_grade: boolean } & Record<string, number | boolean>;

export const nqaKey = (clientDraftId: string) => `offlineNqa:${clientDraftId}`;

interface StoredNqa { answersHash: string; nqa: NarrativeAnswers }

/** The panel's body checked as the online save checks it; throws `offline_nqa_invalid`. */
export function narrativeAnswers(body: Record<string, unknown>): NarrativeAnswers {
  const cannotGrade = body.cannot_grade === true;
  const answers: NarrativeAnswers = { cannot_grade: cannotGrade };
  for (const field of NARRATIVE_QA_FIELDS) {
    // A score point or its digits (the panel sends text), never an empty, null or boolean answer read as 0.
    const raw = body[field.key];
    const value = cannotGrade ? 0 : typeof raw === "number" ? raw : typeof raw === "string" && /^\d+$/.test(raw) ? Number(raw) : NaN;
    if (!cannotGrade && !field.options.some((option) => option.value === value)) throw new Error("offline_nqa_invalid");
    answers[field.key] = value;
  }
  return answers;
}

/** The workspace's `saved` NQA, with the model's rating thresholds (VaNarrativeAssessment.rating). */
export function narrativeSaved(nqa: NarrativeAnswers): NarrativeSaved {
  const values = Object.fromEntries(NARRATIVE_QA_FIELDS.map((field) => [field.key, Number(nqa[field.key])]));
  const score = Object.values(values).reduce((sum, value) => sum + value, 0);
  const rating = nqa.cannot_grade ? "Cannot Grade" : score >= 7 ? "Good" : score >= 5 ? "Fair" : "Poor";
  return { cannot_grade: nqa.cannot_grade, values, score, rating };
}

/** The NQA saved on these answers, or null (none, damaged, or assessed on other answers). */
export async function getOfflineNqa(db: Db, clientDraftId: string, answersHash: string | null): Promise<NarrativeAnswers | null> {
  const stored = await getMeta<StoredNqa>(db, nqaKey(clientDraftId));
  if (!stored || !answersHash || stored.answersHash !== answersHash || !stored.nqa || typeof stored.nqa !== "object") return null;
  try {
    return narrativeAnswers(stored.nqa);
  } catch {
    return null;
  }
}

/** Save the NQA for these answers. A coding the server refused waits on the phone until it changes: this is a change. */
export async function saveOfflineNqa(db: Db, clientDraftId: string, answersHash: string, nqa: NarrativeAnswers): Promise<void> {
  await setMeta(db, nqaKey(clientDraftId), { answersHash, nqa } satisfies StoredNqa);
  await setMeta(db, `coding-refused:${clientDraftId}`, null);
}

/**
 * The `narrative_qa` key of the final's `offline_coding` object: sent where the project asks it (`asked`, the cached
 * switch) or the coder saved one, as the answers coded or null when there is none on them (the server then refuses
 * `narrative_qa_required` where the project asks it). Absent otherwise, as from an older APK.
 */
export async function offlineQualityFields(db: Db, clientDraftId: string, codedAnswersHash: string, asked: boolean): Promise<{ narrative_qa?: NarrativeAnswers | null }> {
  if (!asked && (await getMeta(db, nqaKey(clientDraftId))) === undefined) return {};
  return { narrative_qa: await getOfflineNqa(db, clientDraftId, codedAnswersHash) };
}
