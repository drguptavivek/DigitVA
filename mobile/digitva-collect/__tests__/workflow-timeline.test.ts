import {
  appendWorkflowEvent,
  workflowTimeline,
} from "../src/workflowTimeline";

const at = (second: number) => `2026-10-28T10:00:${String(second).padStart(2, "0")}+05:30`;

test("timeline is ordered, bounded, and first event wins on retry", () => {
  const first = appendWorkflowEvent(undefined, "review_opened", at(3));
  const withStart = appendWorkflowEvent(first, "interview_started", at(1));
  const retried = appendWorkflowEvent(withStart, "review_opened", at(9));

  expect(retried).toEqual([
    { event: "interview_started", at: at(1) },
    { event: "review_opened", at: at(3) },
  ]);
});

test("timeline rejects untrusted shape and elapsed bounds", () => {
  expect(() => workflowTimeline([{ event: "interview_started", at: at(1), extra: true }])).toThrow("invalid_workflow_timeline");
  expect(() => appendWorkflowEvent(undefined, "interview_started", at(1), 86_400_001)).toThrow("invalid_workflow_timeline");
});
