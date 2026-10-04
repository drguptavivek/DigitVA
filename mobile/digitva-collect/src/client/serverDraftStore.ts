import type { SubmissionData, WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

import { ClientApiError, requestClientJson, type ClientCsrf, type DraftResponse } from "./api";
import { readDefinitionPin, withDefinitionPin, type DefinitionPin } from "../formDefinitionRuntime";

type SectionMap = Record<string, Record<string, unknown>>;
type BaselineMap = Record<string, string>;

function splitBySection(data: Record<string, unknown>, sectionOf: ReadonlyMap<string, string>): SectionMap {
  const sections: SectionMap = {};
  for (const [name, value] of Object.entries(data)) {
    const section = sectionOf.get(name) ?? "_other";
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
  identity?: { instrumentId: string; instrumentVersion: string; firstSection: string };
  definitionPin?: DefinitionPin | null;
  locale?: string;
  translationVersion?: number;
  onError?: (error: unknown) => void;
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
  private readonly identity?: ServerDraftStoreOptions["identity"];
  private definitionPin: DefinitionPin | null;
  private readonly onError?: (error: unknown) => void;
  private locale?: string;
  private translationVersion?: number;
  private baseline: BaselineMap = {};
  private baselineLocale: string | undefined;
  private baselineTranslationVersion: number | undefined;
  private baselineDefinitionPin: DefinitionPin | null = null;
  private serverUpdatedAt: string | undefined;
  private draftId: string | undefined;
  private lastSection: string | undefined;
  private pending: WhoVaDraft | undefined;
  private waiters: Array<{ resolve: () => void; reject: (error: unknown) => void }> = [];
  private timer: ReturnType<typeof setTimeout> | undefined;
  private writing: Promise<void> = Promise.resolve();
  private loaded = false;

  constructor(options: ServerDraftStoreOptions) {
    this.endpoint = options.endpoint.replace(/\/$/, "");
    this.csrf = options.csrf;
    this.sectionOf = options.sectionOf;
    this.initialData = options.initialData;
    this.identity = options.identity;
    this.definitionPin = options.definitionPin ?? null;
    this.locale = options.locale;
    this.translationVersion = options.translationVersion;
    this.onError = options.onError;
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
    const savedPin = readDefinitionPin(envelope);
    if (savedPin && this.definitionPin && !sameDefinitionPin(savedPin, this.definitionPin)) {
      throw new ClientApiError(200, "definition_pin_mismatch");
    }
    if (savedPin) this.definitionPin = savedPin;
    const savedData = (envelope.data ?? {}) as Record<string, unknown>;
    // Server drafts can predate fields added by a new registration prefill.
    // Apply those defaults underneath the saved answers so a partial draft is
    // completed without ever replacing an answer already stored on the server.
    const mergedData = this.initialData
      ? { ...(this.initialData as Record<string, unknown>), ...savedData }
      : savedData;
    envelope.data = mergedData as SubmissionData;
    if (!envelope.instrumentVersion && this.definitionPin) envelope.instrumentVersion = this.definitionPin.instrumentVersion;
    if (!envelope.instrumentVersion && this.identity) envelope.instrumentVersion = this.identity.instrumentVersion;
    if (!envelope.instrumentId && this.identity) envelope.instrumentId = this.identity.instrumentId;
    if (!envelope.currentSection && this.identity) envelope.currentSection = this.identity.firstSection;
    this.baselineLocale = envelope.locale ?? this.locale;
    this.baselineTranslationVersion = envelope.translation_version ?? this.translationVersion;
    this.baselineDefinitionPin = savedPin;
    this.baseline = Object.fromEntries(
      // Keep the server's raw answers as the baseline. Defaults newly added
      // by the host prefill must be emitted on the next save, while saved
      // answers remain protected by the merge above.
      Object.entries(splitBySection(savedData, this.sectionOf)).map(([name, value]) => [
        name,
        serialise(value)
      ])
    );
    this.lastSection = envelope.currentSection;
    this.draftId = id;
    this.serverUpdatedAt = response.draft.updated_at;
    this.loaded = true;
    const pinnedEnvelope = withDefinitionPin(envelope, this.definitionPin);
    if (this.definitionPin && !savedPin) await this.writeDraft(pinnedEnvelope);
    return pinnedEnvelope;
  }

  save(draft: WhoVaDraft): Promise<void> {
    if (!this.loaded) return Promise.reject(new Error("Draft must load before it can be saved."));
    this.pending = draft;
    const settled = new Promise<void>((resolve, reject) => this.waiters.push({ resolve, reject }));
    if (this.timer) clearTimeout(this.timer);
    const immediate = draft.currentSection !== this.lastSection;
    this.timer = setTimeout(() => {
      this.timer = undefined;
      void this.flush().catch(() => undefined);
    }, immediate ? 0 : 600);
    return settled;
  }

  async flush(): Promise<void> {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    if (!this.pending) return this.writing;
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
        this.onError?.(error);
        waiters.forEach(({ reject }) => reject(error));
      }
    );
    return write;
  }

  async remove(id: string): Promise<void> {
    await this.flush();
    await requestClientJson(`${this.endpoint}/${encodeURIComponent(id)}/discard`, {
      method: "POST",
      csrf: this.csrf
    });
  }

  private async writeDraft(draft: WhoVaDraft): Promise<void> {
    const sections = splitBySection(draft.data as Record<string, unknown>, this.sectionOf);
    const changed: SectionMap = {};
    // Empty sections must replace their saved answers too.
    for (const name of new Set([...Object.keys(sections), ...Object.keys(this.baseline)])) {
      const answers = sections[name] ?? {};
      if (serialise(answers) !== this.baseline[name]) changed[name] = answers;
    }
    const metadataChanged = this.locale !== this.baselineLocale ||
      this.translationVersion !== this.baselineTranslationVersion ||
      !sameOptionalDefinitionPin(this.definitionPin, this.baselineDefinitionPin);
    if (Object.keys(changed).length === 0 && draft.currentSection === this.lastSection && !metadataChanged) return;
    const acknowledgement = await requestClientJson<{
      saved_sections: number;
      draft: { draft_id: string; updated_at: string };
    }>(`${this.endpoint}/${encodeURIComponent(draft.id)}`, {
      method: "PATCH",
      csrf: this.csrf,
      json: {
        sections: changed,
        current_section: draft.currentSection,
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
          ...(this.translationVersion !== undefined ? { translation_version: this.translationVersion } : {})
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
    for (const [name, answers] of Object.entries(changed)) this.baseline[name] = serialise(answers);
    this.lastSection = draft.currentSection;
    this.baselineLocale = this.locale;
    this.baselineTranslationVersion = this.translationVersion;
    this.baselineDefinitionPin = this.definitionPin;
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
