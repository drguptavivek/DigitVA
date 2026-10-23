/**
 * The one definition of "unsent" for the Sync tab badge, the Home card and the Sync sheet.
 *
 * Unsent = what Send now (syncInterviewer -> uploadQueuedWork + syncQueuedRevisions) will try to upload from this
 * phone, across every project the account holds: completed interviews not yet uploaded, pending registrations,
 * queued contact attempts and visits, and queued (ready) revisions. Drafts still being filled in are NOT unsent;
 * they are counted apart as `inProgress`. Work Send cannot move on its own (refused, needs an edit) is listed as
 * `attention` with its last error and is not in the unsent count, so a Send that succeeds always brings the
 * count down. Counts are exact; the item list is capped at MAX_ITEMS.
 */
import { describeError, recordError } from "./errorLog";
import type { Db } from "./drafts";

export const MAX_ITEMS = 50;
const ERROR_PREFIX = "senderr:";

/** Interview outcomes the server takes without a valid form. */
export const INCOMPLETE_OUTCOMES = ["partially_completed", "respondent_unavailable"] as const;

/** Whether the server will take a completed interview: the form said valid, or the outcome is an incomplete one. */
export function isUploadableVerdict(valid: boolean, outcome: unknown): boolean {
  return valid || (typeof outcome === "string" && (INCOMPLETE_OUTCOMES as readonly string[]).includes(outcome));
}

export type UnsentKind = "interview" | "registration" | "attempt" | "visit" | "revision";

export interface UnsentItem {
  key: string;
  kind: UnsentKind;
  /** The deceased's name when known, else the case ID, else a short local ID. */
  title: string;
  /** ready: Send now will try it. waiting: it follows a registration that is still to be sent. attention: Send cannot move it until someone edits it. */
  state: "ready" | "waiting" | "attention";
  /** The last send error (the Ref line: status, code, route; never answers or names). */
  error?: string;
}

export interface WorkSummary {
  /** Ready to send (ready + waiting items). */
  unsent: number;
  /** Refused or needing an edit; Send now does not clear these. */
  attention: number;
  /** Drafts and revisions still being filled in; never part of unsent. */
  inProgress: number;
  /** Unsent and attention items, at most MAX_ITEMS, attention first. */
  items: UnsentItem[];
}

/** Remember the last send error of one item and file it in the error log. Never throws. */
export async function noteSendError(db: Db, id: string, error: unknown): Promise<void> {
  const what = typeof error === "string" ? error : describeError(error);
  recordError(`send ${what}`);
  try {
    await db.runAsync(
      "INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
      [ERROR_PREFIX + id, JSON.stringify(what)],
    );
  } catch {
    // The error is already in the log; the item just shows no Ref.
  }
}

/** Forget an item's error once it is sent. */
export async function clearSendError(db: Db, id: string): Promise<void> {
  await db.runAsync("DELETE FROM meta WHERE key = ?", [ERROR_PREFIX + id]);
}

interface DraftRecord { id: string; unique_id: string | null; death_id: string | null; client_death_id: string | null; upload_issue: string | null; valid: number | null; outcome: string | null }
interface RegRecord { client_death_id: string; state: string; name: string | null }
interface ActionRecord { client_id: string; kind: string; death_id: string | null; client_death_id: string | null; state: string }
interface RevisionRecord { draft_id: string; state: string; refusal: string | null; va_sid: string | null; name: string | null; given: string | null; surname: string | null }

export async function summariseWork(db: Db): Promise<WorkSummary> {
  const [drafts, regs, actions, revisions, errors, inProgressDrafts] = await Promise.all([
    db.getAllAsync<DraftRecord>(
      `SELECT id, unique_id, death_id, client_death_id, upload_issue,
              json_extract(completion, '$.valid') AS valid, json_extract(envelope, '$.data.interview_outcome') AS outcome
       FROM drafts WHERE completed = 1 AND project_id IS NOT NULL ORDER BY updated_at`, []),
    db.getAllAsync<RegRecord>("SELECT client_death_id, state, json_extract(fields, '$.deceased_name') AS name FROM registrations ORDER BY created_at", []),
    db.getAllAsync<ActionRecord>("SELECT client_id, kind, death_id, client_death_id, state FROM case_actions ORDER BY created_at, client_id", []),
    db.getAllAsync<RevisionRecord>(
      `SELECT draft_id, state, json_extract(row_json, '$.refusal_code') AS refusal, json_extract(row_json, '$.va_sid') AS va_sid,
              json_extract(row_json, '$.deceased_name') AS name, json_extract(row_json, '$.prefill.deceased.givenNames') AS given,
              json_extract(row_json, '$.prefill.deceased.surname') AS surname
       FROM revision_drafts ORDER BY updated_at DESC, draft_id`, []),
    db.getAllAsync<{ key: string; value: string }>("SELECT key, value FROM meta WHERE key LIKE ?", [`${ERROR_PREFIX}%`]),
    db.getFirstAsync<{ n: number }>("SELECT COUNT(*) AS n FROM drafts WHERE completed = 0", []),
  ]);
  const errorOf = new Map<string, string>();
  for (const { key, value } of errors) {
    try { errorOf.set(key.slice(ERROR_PREFIX.length), String(JSON.parse(value))); } catch { /* unreadable: no Ref */ }
  }
  const stuckRegs = new Set(regs.filter((reg) => reg.state !== "pending").map((reg) => reg.client_death_id));
  const items: UnsentItem[] = [];
  const add = (item: Omit<UnsentItem, "error"> & { id: string; issue?: string | null }) => {
    const { id, issue, ...rest } = item;
    items.push({ ...rest, ...((errorOf.get(id) ?? issue) ? { error: errorOf.get(id) ?? issue! } : {}) });
  };

  for (const d of drafts) {
    const waitsOnStuck = Boolean(d.client_death_id && !d.death_id && (!regs.some((r) => r.client_death_id === d.client_death_id) || stuckRegs.has(d.client_death_id!)));
    const ok = !d.upload_issue && isUploadableVerdict(d.valid === 1, d.outcome);
    add({
      key: `d:${d.id}`, id: d.id, kind: "interview", title: d.unique_id ?? d.id.slice(0, 8),
      state: !ok || waitsOnStuck ? "attention" : d.client_death_id && !d.death_id ? "waiting" : "ready",
      issue: d.upload_issue ?? (!ok ? "not_ready" : waitsOnStuck ? "registration_not_sent" : null),
    });
  }
  for (const r of regs) {
    add({ key: `r:${r.client_death_id}`, id: r.client_death_id, kind: "registration", title: r.name ?? r.client_death_id.slice(0, 8), state: r.state === "pending" ? "ready" : "attention", issue: r.state === "pending" ? null : "needs_edit" });
  }
  for (const a of actions) {
    const waits = !a.death_id;
    const bad = a.state !== "pending" || (waits && (!a.client_death_id || stuckRegs.has(a.client_death_id) || !regs.some((r) => r.client_death_id === a.client_death_id)));
    add({ key: `a:${a.client_id}`, id: a.client_id, kind: a.kind === "visit" ? "visit" : "attempt", title: (a.death_id ?? a.client_death_id ?? a.client_id).slice(0, 8), state: bad ? "attention" : waits ? "waiting" : "ready", issue: bad ? (a.state !== "pending" ? "needs_edit" : "registration_not_sent") : null });
  }
  let revisionsEditing = 0;
  for (const v of revisions) {
    if (v.state === "editing") { revisionsEditing += 1; continue; }
    const name = v.name ?? ([v.given, v.surname].filter(Boolean).join(" ") || null);
    add({ key: `v:${v.draft_id}`, id: v.draft_id, kind: "revision", title: name ?? v.va_sid ?? v.draft_id.slice(0, 8), state: v.state === "ready" ? "ready" : "attention", issue: v.refusal });
  }
  const attention = items.filter((item) => item.state === "attention");
  const sendable = items.filter((item) => item.state !== "attention");
  return {
    unsent: sendable.length,
    attention: attention.length,
    inProgress: Number(inProgressDrafts?.n ?? 0) + revisionsEditing,
    items: [...attention, ...sendable].slice(0, MAX_ITEMS),
  };
}
