/** The Home dashboard's numbers from the Interviews items (no extra reads). The unsent count is not here: it is shared (src/unsentWork.ts). */
import type { InterviewItem, InterviewCounts } from "./interviewRows";

export interface HomeSummary {
  /** Drafts still being filled in, most recently edited first. */
  inProgress: InterviewItem[];
  /** Cases waiting for a first interview. */
  needVisit: number;
}

export function homeSummary(items: InterviewItem[], counts: InterviewCounts): HomeSummary {
  const inProgress = items.filter((item) => item.kind === "drafts" && item.action?.type === "resume");
  return { inProgress, needVisit: counts.todo };
}
