/**
 * The last loaded Interviews/Home data, held in memory so a tab opened again draws at once (no skeleton, no count
 * that changes after the project is applied) while it refreshes. One entry, for one interviewer, valid only for the
 * database handle it was read through: a lock (lockAll) or another account makes the handle differ, so it is never
 * served, and the lock/error paths also drop it.
 */
import type { CaseAction, CaseDetail, CaseRow, Registration } from "./cases";
import type { Db } from "./drafts";
import type { ListedDraft } from "./ui/interviewRows";
import type { RevisionRow, SubmittedRevisionSummary } from "./revisions";
import type { SendRefusal } from "./unsentWork";
import type { PausedProject, getCachedReferenceData } from "./sync";
import { unlockedDb } from "./interviewerDb";

export interface WorklistSnapshot {
  drafts: ListedDraft[];
  refusals: Map<string, SendRefusal>;
  revisions: RevisionRow[];
  cases: CaseDetail[];
  registrations: Registration[];
  actions: CaseAction[];
  pausedProjects: PausedProject[];
  submittedRevisions: SubmittedRevisionSummary[];
  onlineCases: CaseRow[];
  referenceData: Awaited<ReturnType<typeof getCachedReferenceData>>;
  selectedProjectId: string | undefined;
}

let held: { userId: string; db: Db; snapshot: WorklistSnapshot } | undefined;

export function holdWorklist(userId: string, db: Db, snapshot: WorklistSnapshot): void {
  held = { userId, db, snapshot };
}

export function heldWorklist(userId: string): WorklistSnapshot | undefined {
  return held && held.userId === userId && unlockedDb(userId) === held.db ? held.snapshot : undefined;
}

export function dropWorklist(): void {
  held = undefined;
}
