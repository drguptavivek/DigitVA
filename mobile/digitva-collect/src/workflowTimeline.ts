/** Small, first-party interview/coding timeline kept beside (never inside) answers. */

export type WorkflowTimelineEvent = {
  event: string;
  at: string;
  elapsed_ms?: number;
};

export const WORKFLOW_TIMELINE_MAX = 8;
export const WORKFLOW_TIMELINE_EVENTS = [
  "interview_started",
  "identity_saved",
  "questionnaire_midpoint",
  "review_opened",
  "submit_started",
  "submitted",
  "coding_allocated",
  "coding_opened",
  "doris_processed",
  "initial_saved",
  "final_saved",
] as const;

const TIMELINE_ORDER = new Map<string, number>(WORKFLOW_TIMELINE_EVENTS.map((event, index) => [event, index]));
const TIMESTAMP_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const MAX_ELAPSED_MS = 86_400_000;

function validTimestamp(value: unknown): value is string {
  return typeof value === "string" && TIMESTAMP_RE.test(value) && !Number.isNaN(Date.parse(value));
}

function validElapsed(value: unknown): value is number {
  return value === undefined || (
    typeof value === "number" && Number.isInteger(value) && value >= 0 && value <= MAX_ELAPSED_MS
  );
}

function checkedEvent(value: unknown): WorkflowTimelineEvent {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid_workflow_timeline");
  const candidate = value as Record<string, unknown>;
  if (Object.keys(candidate).some((key) => !["event", "at", "elapsed_ms"].includes(key))) {
    throw new Error("invalid_workflow_timeline");
  }
  if (typeof candidate.event !== "string" || !TIMELINE_ORDER.has(candidate.event) || !validTimestamp(candidate.at) ||
      !validElapsed(candidate.elapsed_ms)) throw new Error("invalid_workflow_timeline");
  return {
    event: candidate.event,
    at: candidate.at,
    ...(candidate.elapsed_ms === undefined ? {} : { elapsed_ms: candidate.elapsed_ms }),
  };
}

/** Validate and canonicalise an existing timeline, retaining its first event for each name. */
export function workflowTimeline(value: unknown): WorkflowTimelineEvent[] {
  if (value === undefined || value === null) return [];
  if (!Array.isArray(value) || value.length > WORKFLOW_TIMELINE_MAX) throw new Error("invalid_workflow_timeline");
  const seen = new Set<string>();
  const result: WorkflowTimelineEvent[] = [];
  for (const item of value) {
    const event = checkedEvent(item);
    if (seen.has(event.event)) continue;
    seen.add(event.event);
    result.push(event);
  }
  return result.sort((left, right) => TIMELINE_ORDER.get(left.event)! - TIMELINE_ORDER.get(right.event)!);
}

/** Add one bounded, idempotent event. Existing values always win on retries. */
export function appendWorkflowEvent(
  existing: WorkflowTimelineEvent[] | undefined,
  event: string,
  at = new Date().toISOString(),
  elapsedMs?: number,
): WorkflowTimelineEvent[] {
  const current = workflowTimeline(existing);
  if (!TIMELINE_ORDER.has(event) || !validTimestamp(at) || !validElapsed(elapsedMs)) {
    throw new Error("invalid_workflow_timeline");
  }
  if (current.some((entry) => entry.event === event) || current.length >= WORKFLOW_TIMELINE_MAX) return current;
  return workflowTimeline([...current, { event, at, ...(elapsedMs === undefined ? {} : { elapsed_ms: elapsedMs }) }]);
}
