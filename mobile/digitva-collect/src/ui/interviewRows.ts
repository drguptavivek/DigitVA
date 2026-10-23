/**
 * The phone's Interviews list as data (pure, no I/O): every local draft, pending registration, downloaded or
 * fetched case, submitted interview and local revision becomes one item with one status badge and at most one
 * primary action. The same items feed the Home dashboard counts, so the two screens never disagree.
 */
import type { CaseDetail, CaseRow, Registration } from "../cases";
import { canStartDeathInterview } from "../deathWorkflow";
import type { DraftRow } from "../drafts";
import { t } from "../i18n";
import { revisionName } from "../revisionLabel";
import type { RevisionRow, SubmittedRevisionSummary } from "../revisions";
import { matchesSearch } from "./caseSearch";

export type InterviewKind = "drafts" | "todo" | "sent" | "revisions";
export type InterviewFilter = "all" | InterviewKind;
export const INTERVIEW_FILTERS: InterviewFilter[] = ["all", "drafts", "todo", "sent", "revisions"];

export function parseInterviewFilter(value: string | string[] | undefined): InterviewFilter {
  const one = Array.isArray(value) ? value[0] : value;
  return INTERVIEW_FILTERS.includes(one as InterviewFilter) ? (one as InterviewFilter) : "all";
}

export type InterviewAction =
  | { type: "resume"; draft: DraftRow; label: string }
  | { type: "case"; deathId: string; projectId: string; label: string }
  | { type: "registration"; clientDeathId: string; label: string }
  | { type: "revise"; source: SubmittedRevisionSummary | RevisionRow; label: string };

export interface InterviewItem {
  key: string;
  kind: InterviewKind;
  title: string;
  caseId?: string;
  ageYears?: number | null;
  sex?: string | null;
  dateOfDeath?: string | null;
  unit?: string;
  badge: { label: string; tone?: "neutral" | "accent" | "warning" };
  /** Absent when nothing can be done with the row yet (a draft already marked ready to send). */
  action?: InterviewAction;
  /** Extra lines under the facts: server-state notices, upload issues, a revision's status. */
  lines: Array<{ text: string; tone?: "error" }>;
  /** A draft the demo limit refused: the card offers a retry beside its Resume. */
  retryDemo?: DraftRow;
  search: Array<string | null | undefined>;
  updatedAt: string;
}

export interface InterviewSources {
  drafts: DraftRow[];
  registrations: Registration[];
  cases: CaseDetail[];
  onlineCases: CaseRow[];
  submitted: SubmittedRevisionSummary[];
  revisions: RevisionRow[];
}

const TERMINAL_CASE_STATES = new Set(["completed", "submitted", "cancelled", "closed", "duplicate", "not_codeable"]);

/** A downloaded case and a fetched page row, as one flat shape. */
interface FlatCase {
  death_id: string; project_id: string; unique_id: string; state: string; unit_name: string | null;
  name?: string | null; sex?: string | null; age?: number | null; died?: string | null; village?: string | null;
  updated_at: string; other_draft_active?: boolean; other_draft_started_at?: string | null;
  other_complete_interview?: boolean; code_now?: boolean; my_draft_id: string | null;
}

const flatLocal = (row: CaseDetail): FlatCase => ({
  ...row, name: row.deceased?.name, sex: row.deceased?.sex, age: row.deceased?.age_years,
  died: row.deceased?.date_of_death, village: row.household_address?.village_ward,
});
const flatOnline = (row: CaseRow): FlatCase => ({ ...row, name: row.deceased_name, sex: row.deceased_sex, age: row.age_years, died: row.date_of_death });

/** The server time when usable, otherwise the generic "another draft is active" warning. */
function otherDraftWarning(value: string | null | undefined): string {
  const date = value ? new Date(value) : undefined;
  return date && !Number.isNaN(date.getTime()) ? t("otherDraftActiveAt", { date: date.toLocaleString() }) : t("otherDraftActive");
}

function caseLines(row: FlatCase): InterviewItem["lines"] {
  return [
    ...(row.other_draft_active === true ? [{ text: otherDraftWarning(row.other_draft_started_at) }, { text: t("otherDraftSyncNotice") }] : []),
    ...(row.other_complete_interview === true ? [{ text: t("otherCompleteInterviewNotice") }] : []),
    ...(row.code_now === true ? [{ text: t("readyForCodeOnWeb") }] : []),
  ];
}

/** Why a local revision row is where it is (server refusal, saved, retry, or still being edited). */
export function localRevisionStatus(row: RevisionRow): string {
  switch (row.refusal_code) {
    case "revision_locked": return t("revisionLocked");
    case "case_already_submitted": return t("revisionAlreadySubmitted");
    case "case_closed": return t("revisionCaseClosed");
    case "case_state_conflict": return t("revisionCaseConflict");
    case "invalid_reason":
    case "required_finish_partial": return t("revisionInvalidReason");
    case "not_found": return t("revisionUnavailable");
    default:
      if (row.state === "ready") return t("revisionSaved");
      return row.state === "attention" ? t("revisionRetry") : t("draftInProgress");
  }
}

const draftIssueLines = (draft: DraftRow): InterviewItem["lines"] => [
  ...(draft.upload_issue === "answers_hash_invalid" ? [{ text: t("draftHashInvalidAttention"), tone: "error" as const }] : []),
  ...(draft.upload_issue === "demo_limit" ? [{ text: t("demoDraftLimit"), tone: "error" as const }] : []),
];

function dateOnly(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString();
}

/** All items, newest work first within each kind: drafts, revisions, to do, sent. */
export function buildInterviewItems(src: InterviewSources): InterviewItem[] {
  const cases = new Map<string, FlatCase>();
  for (const row of src.onlineCases) cases.set(row.death_id, flatOnline(row));
  for (const row of src.cases) cases.set(row.death_id, flatLocal(row));
  // A case that has a local draft is shown once, as that draft.
  const draftDeaths = new Set(src.drafts.map((draft) => draft.death_id).filter(Boolean));
  const draftIds = new Set(src.drafts.map((draft) => draft.unique_id).filter(Boolean));
  const byUnique = new Map([...cases.values()].map((row) => [row.unique_id, row]));

  const items: InterviewItem[] = [];
  for (const draft of src.drafts) {
    const known = (draft.death_id ? cases.get(draft.death_id) : undefined) ?? (draft.unique_id ? byUnique.get(draft.unique_id) : undefined);
    const ready = draft.completed === 1;
    items.push({
      key: `draft-${draft.id}`, kind: "drafts",
      title: known?.name || draft.unique_id || draft.id.slice(0, 8),
      caseId: known?.name ? known.unique_id : undefined,
      ageYears: known?.age, sex: known?.sex, dateOfDeath: dateOnly(known?.died), unit: known?.unit_name ?? undefined,
      badge: ready ? { label: t("draftReady"), tone: "accent" } : { label: t("badgeDraft"), tone: "warning" },
      action: ready ? undefined : { type: "resume", draft, label: t("actionResume") },
      lines: [...(known ? caseLines(known) : []), ...draftIssueLines(draft)],
      retryDemo: draft.upload_issue === "demo_limit" ? draft : undefined,
      search: [known?.name, draft.unique_id, known?.unique_id, known?.unit_name, known?.village],
      updatedAt: draft.updated_at,
    });
  }
  for (const reg of src.registrations) {
    const attention = reg.state === "needs_edit";
    items.push({
      key: `registration-${reg.client_death_id}`, kind: "drafts", title: reg.fields.deceased_name,
      sex: reg.fields.deceased_sex, dateOfDeath: reg.fields.date_of_death,
      badge: { label: attention ? t("needsEdit") : t("pendingSend"), tone: attention ? "warning" : "neutral" },
      action: { type: "registration", clientDeathId: reg.client_death_id, label: t("viewDetails") },
      lines: [], search: [reg.fields.deceased_name], updatedAt: reg.created_at,
    });
  }
  for (const row of src.revisions) {
    const name = revisionName(row);
    items.push({
      key: `revision-${row.draft_id}`, kind: "revisions", title: name ?? row.unique_id ?? row.draft_id.slice(0, 8),
      caseId: name ? (row.unique_id ?? undefined) : undefined,
      badge: { label: t("badgeRevision"), tone: row.state === "attention" ? "warning" : "accent" },
      action: { type: "revise", source: row, label: t("reviseInterview") },
      lines: [{ text: localRevisionStatus(row), tone: row.state === "attention" ? "error" : undefined }],
      search: [name, row.unique_id], updatedAt: row.updated_at,
    });
  }
  for (const row of cases.values()) {
    if (draftDeaths.has(row.death_id) || draftIds.has(row.unique_id) || row.my_draft_id && src.drafts.some((d) => d.server_draft_id === row.my_draft_id)) continue;
    const terminal = TERMINAL_CASE_STATES.has(row.state);
    const startable = !terminal && canStartDeathInterview(row.state);
    items.push({
      key: `case-${row.death_id}`, kind: terminal ? "sent" : "todo", title: row.name || row.unique_id,
      caseId: row.name ? row.unique_id : undefined, ageYears: row.age, sex: row.sex, dateOfDeath: dateOnly(row.died),
      unit: row.unit_name ?? undefined,
      badge: terminal ? { label: t("badgeSent"), tone: "neutral" } : { label: t("badgeTodo"), tone: "accent" },
      action: { type: "case", deathId: row.death_id, projectId: row.project_id, label: startable ? t("actionStart") : t("viewDetails") },
      lines: caseLines(row),
      search: [row.name, row.unique_id, row.unit_name, row.village], updatedAt: row.updated_at,
    });
  }
  const casedDeaths = new Set(cases.keys());
  for (const row of src.submitted) {
    // A submitted interview whose case is already listed (and not as a draft) is the same row, not a second one.
    if (row.death_id && casedDeaths.has(row.death_id)) continue;
    const name = revisionName(row);
    items.push({
      key: `sent-${row.draft_id}`, kind: "sent", title: name ?? row.unique_id ?? row.draft_id.slice(0, 8),
      caseId: name ? (row.unique_id ?? undefined) : undefined,
      badge: { label: t("badgeSent"), tone: "neutral" },
      action: { type: "revise", source: row, label: t("reviseInterview") }, lines: [],
      search: [name, row.unique_id], updatedAt: row.updated_at ?? "",
    });
  }
  const order: Record<InterviewKind, number> = { drafts: 0, revisions: 1, todo: 2, sent: 3 };
  return items.sort((a, b) => order[a.kind] - order[b.kind] || (b.updatedAt ?? "").localeCompare(a.updatedAt ?? ""));
}

export type InterviewCounts = Record<InterviewFilter, number>;

export function interviewCounts(items: InterviewItem[]): InterviewCounts {
  const counts: InterviewCounts = { all: items.length, drafts: 0, todo: 0, sent: 0, revisions: 0 };
  for (const item of items) counts[item.kind] += 1;
  return counts;
}

export function filterInterviews(items: InterviewItem[], filter: InterviewFilter, query: string): InterviewItem[] {
  return items.filter((item) => (filter === "all" || item.kind === filter) && matchesSearch(item.search, query));
}
