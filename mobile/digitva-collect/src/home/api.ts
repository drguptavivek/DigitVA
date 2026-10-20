/** Personal activity counts for the signed-in user's Home / Dashboard (digitva-dsj2). */
import type { JsonRequester } from "../workspace/api";

const ACTIVITY_API = "/api/v1/me/activity";

export interface UserActivityCounts {
  deaths_reported: number;
  interviews_submitted: number;
  drafts_in_progress: number;
  coded: number;
  not_codeable: number;
  reviewed: number;
}

export interface UserActivitySummary {
  totals: UserActivityCounts;
  by_project: Record<string, UserActivityCounts>;
}

export const EMPTY_ACTIVITY_COUNTS: UserActivityCounts = {
  deaths_reported: 0,
  interviews_submitted: 0,
  drafts_in_progress: 0,
  coded: 0,
  not_codeable: 0,
  reviewed: 0,
};

export async function getMyActivity(request: JsonRequester): Promise<UserActivitySummary> {
  const reply = (await request(ACTIVITY_API)) as Partial<UserActivitySummary> | null;
  return {
    totals: reply?.totals ?? EMPTY_ACTIVITY_COUNTS,
    by_project: reply?.by_project ?? {},
  };
}
