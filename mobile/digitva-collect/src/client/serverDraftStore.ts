import type { SubmissionData, WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

import { ClientApiError, isSignedOutError, requestClientJson, type ClientCsrf, type DraftResponse } from "./api";
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
  private readonly onSaveAcknowledged?: (info: { savedSections: number; updatedAt?: string }) => void;
  private locale?: string;
  private translationVersion?: number;
  private baseline: BaselineMap = {};
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
    const kept = readKeptDraft(id, response.draft.updated_at);
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
    if (this.refusalMode) draft = { ...draft, data: refusalAnswers(draft.data) as SubmissionData };
    this.latestDraft = draft;
    this.noteWorkflowMilestones(draft);
    this.pending = draft;
    if (this.signedOut) {
      keepDraft(draft, this.serverUpdatedAt);
      return Promise.reject(new ClientApiError(401, "unauthorized"));
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
    if (!this.pending) return this.writing;
    if (this.signedOut) throw new ClientApiError(401, "unauthorized");
    const draft = this.pending;
    this.pending = undefined;
    const waiters = this.waiters;
    this.waiters = [];
    const write = this.writing.catch(() => undefined).then(() => this.writeDraft(draft));
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

  private async writeDraft(draft: WhoVaDraft, options?: { isPinOnly?: boolean }): Promise<void> {
    const sections = splitBySection({ ...this.retained, ...(draft.data as Record<string, unknown>) }, this.sectionOf);
    const changed: SectionMap = {};
    // Empty sections must replace their saved answers too.
    for (const name of new Set([...Object.keys(sections), ...Object.keys(this.baseline)])) {
      const answers = sections[name] ?? {};
      if (serialise(answers) !== this.baseline[name]) changed[name] = answers;
    }
    if (this.retainedUnwritten && Object.keys(changed).length > 0) {
      changed[RETAINED_SECTION] = sections[RETAINED_SECTION] ?? {};
    }
    const metadataChanged = this.locale !== this.baselineLocale ||
      this.translationVersion !== this.baselineTranslationVersion ||
      !sameOptionalDefinitionPin(this.definitionPin, this.baselineDefinitionPin) ||
      serialise(this.workflowTimeline) !== serialise(this.baselineWorkflowTimeline);
    if (Object.keys(changed).length === 0 && draft.currentSection === this.lastSection && !metadataChanged) return;
    const acknowledgement = await requestClientJson<{
      saved_sections: number;
      draft: { draft_id: string; updated_at: string };
    }>(`${this.endpoint}/${encodeURIComponent(draft.id)}`, {
      method: "PATCH",
      csrf: this.csrf,
      json: {
        sections: changed,
        ...(draft.currentSection ? { current_section: draft.currentSection } : {}),
        if_updated_at: this.serverUpdatedAt,
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

function readKeptDraft(id: string, serverUpdatedAt: string): Record<string, unknown> | undefined {
  try {
    const raw = keptStorage()?.getItem(KEPT_PREFIX + id);
    const value: unknown = raw ? JSON.parse(raw) : undefined;
    if (!value || typeof value !== "object" || Array.isArray(value)) return undefined;
    const kept = value as { data?: unknown; baseUpdatedAt?: unknown };
    if (kept.baseUpdatedAt !== serverUpdatedAt || !kept.data || typeof kept.data !== "object" || Array.isArray(kept.data)) {
      forgetKeptDraft(id);
      return undefined;
    }
    return kept.data as Record<string, unknown>;
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
