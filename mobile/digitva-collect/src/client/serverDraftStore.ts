import type { SubmissionData, WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

import { ClientApiError, isSignedOutError, readLastChange, requestClientJson, type ClientCsrf, type DraftLastChange, type DraftResponse } from "./api";
import { readDefinitionPin, withDefinitionPin, type DefinitionPin } from "../formDefinitionRuntime";
import { refusalAnswers } from "../refusalBoundary";
import {
  appendWorkflowEvent,
  workflowTimeline,
  type WorkflowTimelineEvent,
} from "../workflowTimeline";

type SectionMap = Record<string, Record<string, unknown>>;
type BaselineMap = Record<string, string>;

/** The section answers to names outside the form's questions are saved in. */
const RETAINED_SECTION = "_other";

function splitBySection(data: Record<string, unknown>, sectionOf: ReadonlyMap<string, string>): SectionMap {
  const sections: SectionMap = {};
  for (const [name, value] of Object.entries(data)) {
    const section = sectionOf.get(name) ?? RETAINED_SECTION;
    (sections[section] ??= {})[name] = value;
  }
  return sections;
}

function serialise(value: unknown): string {
  return JSON.stringify(value ?? null);
}

/**
 * A save the server refused (4xx other than a dead session, a timeout or a rate limit): sending the same
 * answers again is refused the same way, so autosave stops instead of resending them every few seconds.
 */
function isRefusedSave(error: unknown): boolean {
  return error instanceof ClientApiError && error.status >= 400 && error.status < 500 &&
    error.status !== 408 && error.status !== 429;
}

export interface ServerDraftStoreOptions {
  endpoint: string;
  csrf: ClientCsrf;
  sectionOf: ReadonlyMap<string, string>;
  initialData?: SubmissionData;
  initialDataVersion?: string;
  identity?: { instrumentId: string; instrumentVersion: string; firstSection: string };
  definitionPin?: DefinitionPin | null;
  locale?: string;
  translationVersion?: number;
  onError?: (error: unknown) => void;
  /** The cookie session is dead: autosave is paused and the pending answers are kept on this device. */
  onSignedOut?: () => void;
  /** The server refused a save: autosave is paused, the pending answers are kept on this device, `retrySave` resends. */
  onSaveHeld?: (error: unknown) => void;
  onSaveAcknowledged?: (info: { savedSections: number; updatedAt?: string }) => void;
}

export interface DraftLocaleMetadata {
  locale?: string;
  translationVersion?: number;
}

/** Server-backed WHO draft store. It never uses localStorage or IndexedDB. */
export class ServerDraftStore implements WhoVaDraftStore {
  private readonly endpoint: string;
  private readonly csrf: ClientCsrf;
  private readonly sectionOf: ReadonlyMap<string, string>;
  private readonly initialData?: SubmissionData;
  private initialDataVersion?: string;
  private readonly identity?: ServerDraftStoreOptions["identity"];
  private definitionPin: DefinitionPin | null;
  private readonly onError?: (error: unknown) => void;
  private readonly onSignedOut?: () => void;
  private signedOut = false;
  private readonly onSaveHeld?: (error: unknown) => void;
  // The refusal that paused autosave, until the user asks to try again.
  private held: unknown = undefined;
  // "Keep the newer version": this tab's answers are given up; nothing is saved or kept from here on.
  private abandoned = false;
  // Answers this tab kept (a held save) that a later change on the server overtook; offered at load.
  private staleKept: { data: Record<string, unknown>; change: DraftLastChange } | undefined;
  private loadedEnvelope: WhoVaDraft | undefined;
  private readonly onSaveAcknowledged?: (info: { savedSections: number; updatedAt?: string }) => void;
  private locale?: string;
  private translationVersion?: number;
  private baseline: BaselineMap = {};
  // Answers present in the loaded draft that a save has not yet cleared: a
  // cleared one goes out as an explicit null, because the server cannot tell
  // a cleared question from one never asked (a phone-won draft's copy would
  // come back, digitva-k00b).
  private loadedAnswerKeys = new Set<string>();
  // Saved answers to questions this form does not ask (a draft moved to a
  // newer form). The form never sees them, so every save carries them back,
  // in the section splitBySection gives unknown names.
  private retained: Record<string, unknown> = {};
  // The first answer save writes that section: the server replaces a whole
  // section row, and the rows they were saved in are rewritten without them.
  // Not at load, which must not date the draft over a newer phone save.
  private retainedUnwritten = false;
  private baselineLocale: string | undefined;
  private baselineTranslationVersion: number | undefined;
  private baselineDefinitionPin: DefinitionPin | null = null;
  private workflowTimeline: WorkflowTimelineEvent[] = [];
  private baselineWorkflowTimeline: WorkflowTimelineEvent[] = [];
  private serverUpdatedAt: string | undefined;
  private draftId: string | undefined;
  private lastSection: string | undefined;
  private pending: WhoVaDraft | undefined;
  private latestDraft: WhoVaDraft | undefined;
  private waiters: Array<{ resolve: () => void; reject: (error: unknown) => void }> = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private writing: Promise<void> = Promise.resolve();
  private loaded = false;
  private refusalMode = false;

  private noHeld = false;

  /** While the interviewer is asked to confirm a consent No, a draft holding it is not saved (the server wipes on it). */
  holdNo(on: boolean): void {
    this.noHeld = on;
  }

  enterRefusal(): void {
    this.refusalMode = true;
    this.retained = {};
    const id = this.draftId ?? this.pending?.id ?? this.latestDraft?.id;
    if (id) forgetKeptDraft(id);
    if (this.pending) this.pending = { ...this.pending, data: refusalAnswers(this.pending.data) as SubmissionData };
    if (this.latestDraft) this.latestDraft = { ...this.latestDraft, data: refusalAnswers(this.latestDraft.data) as SubmissionData };
  }

  constructor(options: ServerDraftStoreOptions) {
    this.endpoint = options.endpoint.replace(/\/$/, "");
    this.csrf = options.csrf;
    this.sectionOf = options.sectionOf;
    this.initialData = options.initialData;
    this.initialDataVersion = options.initialDataVersion;
    this.identity = options.identity;
    this.definitionPin = options.definitionPin ?? null;
    this.locale = options.locale;
    this.translationVersion = options.translationVersion;
    this.onError = options.onError;
    this.onSignedOut = options.onSignedOut;
    this.onSaveHeld = options.onSaveHeld;
    this.onSaveAcknowledged = options.onSaveAcknowledged;
  }

  setLocaleMetadata(locale: string, translationVersion: number | undefined): void {
    this.locale = locale;
    this.translationVersion = translationVersion;
  }

  getLocaleMetadata(): DraftLocaleMetadata {
    return { locale: this.locale, translationVersion: this.translationVersion };
  }

  getServerUpdatedAt(): string | undefined {
    return this.serverUpdatedAt;
  }

  /** A newly granted DP decision acknowledges the latest cleared draft before editing resumes. */
  async resumeAfterConsentGrant(): Promise<void> {
    if (!this.draftId) throw new Error("Draft must load before consent can be resumed.");
    const path = `${this.endpoint}/${encodeURIComponent(this.draftId)}`;
    const current = await requestClientJson<DraftResponse>(path, { csrf: this.csrf });
    if (!current.draft.updated_at) throw new ClientApiError(200, "malformed_response");
    // A WHO refusal is a separate decision and needs its own explicit correction.
    if (current.envelope.data?.Id10013 === "no") return;
    await requestClientJson(path, { method: "PATCH", csrf: this.csrf, json: {
      sections: {}, resume_refused: true, if_updated_at: current.draft.updated_at,
    } });
  }

  restoreLocaleMetadata(metadata: DraftLocaleMetadata): void {
    this.locale = metadata.locale;
    this.translationVersion = metadata.translationVersion;
  }

  async load(id: string): Promise<WhoVaDraft | undefined> {
    const response = await requestClientJson<DraftResponse>(`${this.endpoint}/${encodeURIComponent(id)}`, {
      csrf: this.csrf
    });
    if (response.draft.draft_id !== id || typeof response.draft.updated_at !== "string" || !response.draft.updated_at) {
      throw new ClientApiError(200, "malformed_response");
    }
    const envelope = response.envelope;
    try {
      const envelopeRecord = envelope as unknown as Record<string, unknown>;
      const storedTimeline = envelopeRecord.workflowTimelineV1;
      const fallbackTimeline = storedTimeline === undefined && typeof envelope.createdAt === "string"
        && !Number.isNaN(Date.parse(envelope.createdAt))
        ? [{ event: "interview_started", at: envelope.createdAt }]
        : storedTimeline;
      this.workflowTimeline = workflowTimeline(fallbackTimeline);
    } catch {
      throw new ClientApiError(200, "malformed_response");
    }
    this.baselineWorkflowTimeline = this.workflowTimeline;
    const savedPin = readDefinitionPin(envelope);
    if (savedPin && this.definitionPin && !sameDefinitionPin(savedPin, this.definitionPin)) {
      throw new ClientApiError(200, "definition_pin_mismatch");
    }
    if (savedPin) this.definitionPin = savedPin;
    const savedData = (envelope.data ?? {}) as Record<string, unknown>;
    const serverCurrentSection =
      envelope.currentSection ||
      (typeof response.draft?.current_section === "string" ? response.draft.current_section : "");
    // Server drafts can predate fields added by a new registration prefill.
    // Apply those defaults underneath the saved answers so a partial draft is
    // completed without ever replacing an answer already stored on the server.
    // Answers kept on this tab after a dead session come back over the server's (digitva-fvbc).
    const stored = readKeptDraft(id);
    const kept = stored?.baseUpdatedAt === response.draft.updated_at ? stored.data : undefined;
    this.staleKept = undefined;
    if (stored && !kept) {
      // Overtaken by a newer server version: offered as a choice, never merged. A refusal (or a server that
      // does not say who changed it) drops it, so refused answers are never restored.
      const change = readLastChange(response.last_change);
      if (change && !change.refusal) this.staleKept = { data: stored.data, change };
      else forgetKeptDraft(id);
    }
    const prefillApplies = Boolean(this.initialData) && (!this.initialDataVersion || this.initialDataVersion === response.draft.updated_at);
    const mergedData = {
      ...(prefillApplies ? (this.initialData as Record<string, unknown>) : {}),
      ...savedData,
      ...(kept ?? {}),
    };
    envelope.data = mergedData as SubmissionData;
    if (!envelope.instrumentVersion && this.definitionPin) envelope.instrumentVersion = this.definitionPin.instrumentVersion;
    if (!envelope.instrumentVersion && this.identity) envelope.instrumentVersion = this.identity.instrumentVersion;
    if (!envelope.instrumentId && this.identity) envelope.instrumentId = this.identity.instrumentId;
    if (!envelope.currentSection && this.identity) envelope.currentSection = this.identity.firstSection;
    this.baselineLocale = envelope.locale ?? this.locale;
    this.baselineTranslationVersion = envelope.translation_version ?? this.translationVersion;
    this.baselineDefinitionPin = savedPin;
    this.retained = Object.fromEntries(Object.entries(savedData).filter(([name]) => !this.sectionOf.has(name)));
    this.retainedUnwritten = Object.keys(this.retained).length > 0;
    this.loadedAnswerKeys = new Set(Object.keys(savedData).filter((name) => this.sectionOf.has(name)));
    this.baseline = Object.fromEntries(
      // Keep the server's raw answers as the baseline. Defaults newly added
      // by the host prefill must be emitted on the next save, while saved
      // answers remain protected by the merge above.
      Object.entries(splitBySection(savedData, this.sectionOf)).map(([name, value]) => [
        name,
        serialise(value)
      ])
    );
    this.lastSection = serverCurrentSection;
    this.draftId = id;
    this.serverUpdatedAt = response.draft.updated_at;
    this.loaded = true;
    const pinnedEnvelope = withDefinitionPin(envelope, this.definitionPin);
    this.loadedEnvelope = { ...pinnedEnvelope, data: savedData as SubmissionData, currentSection: serverCurrentSection };
    if (this.definitionPin && !savedPin) {
      await this.writeDraft(
        { ...pinnedEnvelope, data: savedData as SubmissionData, currentSection: serverCurrentSection },
        { isPinOnly: true }
      );
      // That write moved updated_at but changed no answer: the form's own load
      // must still find the prefill current, or every prefilled answer is lost
      // while its lock stays (Id10010 read-only and empty, digitva-k7m4).
      if (prefillApplies && this.initialDataVersion) this.initialDataVersion = this.serverUpdatedAt;
    }
    return pinnedEnvelope;
  }

  save(draft: WhoVaDraft): Promise<void> {
    if (!this.loaded) return Promise.reject(new Error("Draft must load before it can be saved."));
    if (this.abandoned) return Promise.resolve();
    if (this.noHeld && draft.data.Id10013 === "no") return Promise.resolve();
    if (this.refusalMode) draft = { ...draft, data: refusalAnswers(draft.data) as SubmissionData };
    this.latestDraft = draft;
    this.noteWorkflowMilestones(draft);
    this.pending = draft;
    if (this.signedOut) {
      keepDraft(draft, this.serverUpdatedAt);
      return Promise.reject(new ClientApiError(401, "unauthorized"));
    }
    if (this.held !== undefined) {
      keepDraft(draft, this.serverUpdatedAt);
      return Promise.reject(this.held);
    }
    const settled = new Promise<void>((resolve, reject) => this.waiters.push({ resolve, reject }));
    if (this.timer) clearTimeout(this.timer);
    const immediate = draft.currentSection !== this.lastSection;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flush().catch(() => undefined);
    }, immediate ? 0 : 600);
    return settled;
  }

  /** Record a submit/transition milestone and flush it through the existing coalesced writer. */
  async recordTimelineEvent(event: string, at?: string, elapsedMs?: number): Promise<void> {
    this.workflowTimeline = appendWorkflowEvent(this.workflowTimeline, event, at, elapsedMs);
    if (!this.latestDraft) return;
    this.pending = this.latestDraft;
    await this.flush();
  }

  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    if (!this.pending || this.abandoned) return this.writing;
    if (this.signedOut) throw new ClientApiError(401, "unauthorized");
    if (this.held !== undefined) throw this.held;
    const draft = this.pending;
    this.pending = undefined;
    const waiters = this.waiters;
    this.waiters = [];
    return this.send(draft, waiters);
  }

  private send(
    draft: WhoVaDraft,
    waiters: Array<{ resolve: () => void; reject: (error: unknown) => void }>,
    options?: { overwrite?: string },
  ): Promise<void> {
    const write = this.writing.catch(() => undefined).then(() => this.writeDraft(draft, options));
    this.writing = write;
    write.then(
      () => waiters.forEach(({ resolve }) => resolve()),
      (error) => {
        if (!this.pending) this.pending = draft;
        if (isSignedOutError(error)) {
          // A dead session cannot be revived by retrying: stop, keep the answers, ask for sign-in.
          this.signedOut = true;
          keepDraft(this.pending, this.serverUpdatedAt);
          this.onSignedOut?.();
        } else if (isRefusedSave(error)) {
          // The form saves on every change and every 20 s: without this hold one refused save
          // became a request every 20 s for as long as the tab stayed open.
          this.held = error;
          keepDraft(this.pending, this.serverUpdatedAt);
          this.onError?.(error);
          this.onSaveHeld?.(error);
        } else {
          this.onError?.(error);
        }
        waiters.forEach(({ reject }) => reject(error));
      }
    );
    return write;
  }

  isSignedOut(): boolean {
    return this.signedOut;
  }

  isSaveHeld(): boolean {
    return this.held !== undefined;
  }

  /** The user's "Try saving again" after a refused save: send the held answers once more (held again if refused). */
  async retrySave(): Promise<void> {
    this.held = undefined;
    await this.flush();
  }

  /** The newer server version a held `draft_stale` refusal reported (who changed it, when), else undefined. */
  heldStaleChange(): { updatedAt: string; change: DraftLastChange } | undefined {
    const error = this.held;
    if (!(error instanceof ClientApiError) || error.code !== "draft_stale") return undefined;
    const change = readLastChange(error.payload?.last_change);
    const updatedAt = error.payload?.updated_at;
    return change && typeof updatedAt === "string" ? { updatedAt, change } : undefined;
  }

  /**
   * "Use my answers" on a held `draft_stale`: replace the server's draft, whole, with this page's answers, based
   * on the version the refusal showed the user (a still newer one is refused again and held with its details).
   */
  async useMyAnswers(): Promise<void> {
    const stale = this.heldStaleChange();
    const draft = this.pending ?? this.latestDraft;
    if (!stale || stale.change.refusal || !draft) throw new Error("No stale save to replace the draft with.");
    this.held = undefined;
    this.pending = undefined;
    await this.send(draft, [], { overwrite: stale.updatedAt });
  }

  /** "Keep the newer version": give up this page's unsaved answers; the caller reloads the draft. */
  keepNewerVersion(): void {
    this.abandoned = true;
    this.held = undefined;
    this.pending = undefined;
    this.writing = Promise.resolve();
    this.waiters.forEach(({ resolve }) => resolve());
    this.waiters = [];
    const id = this.draftId ?? this.latestDraft?.id;
    if (id) forgetKeptDraft(id);
  }

  /** Answers this tab kept before a newer server change overtook them (found at load), and who made that change. */
  overtakenAnswers(): DraftLastChange | undefined {
    return this.staleKept?.change;
  }

  /** "Use my answers" at load: replace the server's draft with the kept answers; the caller reloads to show them. */
  async useOvertakenAnswers(): Promise<void> {
    const stale = this.staleKept;
    if (!stale || !this.draftId || !this.serverUpdatedAt) throw new Error("No kept answers to use.");
    if (!this.loadedEnvelope) throw new Error("No kept answers to use.");
    await this.send({ ...this.loadedEnvelope, data: stale.data as SubmissionData }, [], { overwrite: this.serverUpdatedAt });
    this.staleKept = undefined;
    forgetKeptDraft(this.draftId);
  }

  /** "Keep the newer version" at load: drop the kept answers. */
  discardOvertakenAnswers(): void {
    this.staleKept = undefined;
    if (this.draftId) forgetKeptDraft(this.draftId);
  }

  /** After the user signed in again: take a fresh token, then send what was held back. Throws while still signed out. */
  async resume(): Promise<void> {
    await requestClientJson("/api/v1/me/access");
    this.signedOut = false;
    await this.flush();
  }

  async remove(id: string): Promise<void> {
    await this.flush();
    await requestClientJson(`${this.endpoint}/${encodeURIComponent(id)}/discard`, {
      method: "POST",
      csrf: this.csrf
    });
  }

  /** *overwrite*: the server `updated_at` a "Use my answers" replaces; every section is sent and the rest emptied. */
  private async writeDraft(draft: WhoVaDraft, options?: { isPinOnly?: boolean; overwrite?: string }): Promise<void> {
    const sections = splitBySection({ ...this.retained, ...(draft.data as Record<string, unknown>) }, this.sectionOf);
    const overwrite = options?.overwrite;
    if (overwrite) {
      for (const name of Object.keys(this.baseline)) this.baseline[name] = "";
      this.retainedUnwritten = true;
    }
    const changed: SectionMap = {};
    // Empty sections must replace their saved answers too.
    for (const name of new Set([...Object.keys(sections), ...Object.keys(this.baseline)])) {
      const answers = sections[name] ?? {};
      if (serialise(answers) !== this.baseline[name]) changed[name] = answers;
    }
    if (this.retainedUnwritten && Object.keys(changed).length > 0) {
      changed[RETAINED_SECTION] = sections[RETAINED_SECTION] ?? {};
    }
    // Explicit nulls for loaded answers now absent; the baseline stays null-free.
    const wire: SectionMap = {};
    for (const [name, answers] of Object.entries(changed)) {
      const nulls: Record<string, null> = {};
      for (const key of this.loadedAnswerKeys) {
        if (this.sectionOf.get(key) === name && (answers[key] === undefined || answers[key] === null)) nulls[key] = null;
      }
      wire[name] = { ...answers, ...nulls };
    }
    const metadataChanged = this.locale !== this.baselineLocale ||
      this.translationVersion !== this.baselineTranslationVersion ||
      !sameOptionalDefinitionPin(this.definitionPin, this.baselineDefinitionPin) ||
      serialise(this.workflowTimeline) !== serialise(this.baselineWorkflowTimeline);
    if (!overwrite && Object.keys(changed).length === 0 && draft.currentSection === this.lastSection && !metadataChanged) return;
    const acknowledgement = await requestClientJson<{
      saved_sections: number;
      draft: { draft_id: string; updated_at: string };
    }>(`${this.endpoint}/${encodeURIComponent(draft.id)}`, {
      method: "PATCH",
      csrf: this.csrf,
      json: {
        sections: wire,
        ...(draft.currentSection ? { current_section: draft.currentSection } : {}),
        if_updated_at: overwrite ?? this.serverUpdatedAt,
        ...(overwrite ? { overwrite: true } : {}),
        meta: {
          schemaVersion: draft.schemaVersion,
          formVersion: draft.formVersion,
          instrumentId: draft.instrumentId,
          instrumentVersion: this.definitionPin?.instrumentVersion ?? draft.instrumentVersion,
          createdAt: draft.createdAt,
          updatedAt: draft.updatedAt,
          ...(this.definitionPin ? {
            definitionSha256: this.definitionPin.definitionSha256,
            definitionExtensions: [...this.definitionPin.definitionExtensions],
          } : {}),
          ...(this.locale ? { locale: this.locale } : {}),
          ...(this.translationVersion !== undefined ? { translation_version: this.translationVersion } : {}),
          workflowTimelineV1: this.workflowTimeline,
        }
      }
    });
    if (
      !acknowledgement ||
      !Number.isInteger(acknowledgement.saved_sections) ||
      acknowledgement.saved_sections < 0 ||
      acknowledgement.draft?.draft_id !== this.draftId ||
      typeof acknowledgement.draft.updated_at !== "string" ||
      !acknowledgement.draft.updated_at
    ) {
      throw new ClientApiError(200, "malformed_response");
    }
    this.serverUpdatedAt = acknowledgement.draft.updated_at;
    if (!options?.isPinOnly && !this.pending) forgetKeptDraft(draft.id);
    for (const [name, answers] of Object.entries(changed)) this.baseline[name] = serialise(answers);
    for (const answers of Object.values(wire)) {
      for (const [key, value] of Object.entries(answers)) if (value === null) this.loadedAnswerKeys.delete(key);
    }
    if (Object.hasOwn(changed, RETAINED_SECTION)) this.retainedUnwritten = false;
    this.lastSection = draft.currentSection;
    this.baselineLocale = this.locale;
    this.baselineTranslationVersion = this.translationVersion;
    this.baselineDefinitionPin = this.definitionPin;
    this.baselineWorkflowTimeline = this.workflowTimeline;
    if (!options?.isPinOnly) {
      const savedSections =
        acknowledgement.saved_sections > 0
          ? acknowledgement.saved_sections
          : Object.values(this.baseline).filter((value) => value !== "{}").length;
      this.onSaveAcknowledged?.({ savedSections, updatedAt: this.serverUpdatedAt });
    }
  }

  private noteWorkflowMilestones(draft: WhoVaDraft): void {
    this.workflowTimeline = appendWorkflowEvent(this.workflowTimeline, "interview_started");
    const data = draft.data as Record<string, unknown>;
    const identityKeys = ["deceased_name", "date_of_death", "Id10019"];
    if (identityKeys.some((key) => typeof data[key] === "string" && data[key].trim())) {
      this.workflowTimeline = appendWorkflowEvent(this.workflowTimeline, "identity_saved");
    }
    const sections = [...new Set(this.sectionOf.values())];
    const index = sections.indexOf(draft.currentSection);
    if (index >= Math.ceil(sections.length / 2)) {
      this.workflowTimeline = appendWorkflowEvent(this.workflowTimeline, "questionnaire_midpoint");
    }
    if (draft.currentSection.toLowerCase().includes("review")) {
      this.workflowTimeline = appendWorkflowEvent(this.workflowTimeline, "review_opened");
    }
  }
}

const KEPT_PREFIX = "digitva-kept-draft:";

function keptStorage(): Storage | undefined {
  try {
    return typeof sessionStorage === "undefined" ? undefined : sessionStorage;
  } catch {
    return undefined;
  }
}

/** Mirror unsent answers to this tab's sessionStorage (cleared when the tab closes, survives a reload). */
function keepDraft(draft: WhoVaDraft | undefined, baseUpdatedAt: string | undefined): void {
  if (!draft || !baseUpdatedAt) return;
  try {
    keptStorage()?.setItem(KEPT_PREFIX + draft.id, JSON.stringify({ data: draft.data, baseUpdatedAt }));
  } catch {
    // Storage full or blocked: the open tab still holds the answers.
  }
}

/** This tab's kept answers for *id* and the server version they were based on; a malformed entry is dropped. */
function readKeptDraft(id: string): { data: Record<string, unknown>; baseUpdatedAt: string } | undefined {
  try {
    const raw = keptStorage()?.getItem(KEPT_PREFIX + id);
    const value: unknown = raw ? JSON.parse(raw) : undefined;
    if (!value) return undefined;
    const kept = value as { data?: unknown; baseUpdatedAt?: unknown };
    if (typeof value !== "object" || Array.isArray(value) || typeof kept.baseUpdatedAt !== "string" ||
        !kept.data || typeof kept.data !== "object" || Array.isArray(kept.data)) {
      forgetKeptDraft(id);
      return undefined;
    }
    return { data: kept.data as Record<string, unknown>, baseUpdatedAt: kept.baseUpdatedAt };
  } catch {
    return undefined;
  }
}

function forgetKeptDraft(id: string): void {
  try {
    keptStorage()?.removeItem(KEPT_PREFIX + id);
  } catch {
    // Nothing to clear.
  }
}

function sameOptionalDefinitionPin(left: DefinitionPin | null, right: DefinitionPin | null): boolean {
  if (!left || !right) return left === right;
  return sameDefinitionPin(left, right);
}

function sameDefinitionPin(left: DefinitionPin, right: DefinitionPin): boolean {
  return left.instrumentVersion === right.instrumentVersion &&
    left.definitionSha256 === right.definitionSha256 &&
    left.definitionExtensions.length === right.definitionExtensions.length &&
    left.definitionExtensions.every((extension, index) => extension === right.definitionExtensions[index]);
}
