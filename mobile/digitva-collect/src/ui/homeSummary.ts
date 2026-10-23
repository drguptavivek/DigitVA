/** The Home dashboard's numbers, from the same local items the Interviews list shows (no extra reads). */
import type { InterviewItem, InterviewCounts } from "./interviewRows";

export interface HomeSummary {
  /** Drafts still being filled in, most recently edited first. */
  inProgress: InterviewItem[];
  /** Not acknowledged by the server: drafts, pending registrations, revisions and queued case actions on this phone (the four tables countUnsentWork counts). */
  unsent: number;
  /** Cases waiting for a first interview. */
  needVisit: number;
}

export function homeSummary(items: InterviewItem[], counts: InterviewCounts, queuedActions: number): HomeSummary {
  const inProgress = items.filter((item) => item.kind === "drafts" && item.action?.type === "resume");
  return { inProgress, unsent: counts.drafts + counts.revisions + queuedActions, needVisit: counts.todo };
}
