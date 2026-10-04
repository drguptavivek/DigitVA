import type { WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

type RevisionDraft = WhoVaDraft & {
  startedAt?: string;
  completedAt?: string;
  locale?: string;
  translation_version?: number;
};

/** Keep a submitted interview's editable copy in memory for this mounted screen only. */
export class RevisionMemoryStore implements WhoVaDraftStore {
  private draft: RevisionDraft | undefined;
  private readonly retainedMetadata: Pick<RevisionDraft, "startedAt" | "completedAt" | "locale" | "translation_version">;

  constructor(draft: RevisionDraft) {
    this.draft = { ...draft };
    this.retainedMetadata = {
      ...(draft.startedAt ? { startedAt: draft.startedAt } : {}),
      ...(draft.completedAt ? { completedAt: draft.completedAt } : {}),
      ...(draft.locale ? { locale: draft.locale } : {}),
      ...(draft.translation_version !== undefined ? { translation_version: draft.translation_version } : {})
    };
  }

  load(id: string): WhoVaDraft | undefined {
    return this.draft?.id === id ? this.draft : undefined;
  }

  save(draft: WhoVaDraft): void {
    if (this.draft?.id === draft.id) {
      this.draft = { ...draft, ...this.retainedMetadata };
    }
  }

  remove(id: string): void {
    if (this.draft?.id === id) this.draft = undefined;
  }

  getCurrent(): RevisionDraft | undefined {
    return this.draft;
  }

  setLocaleMetadata(locale: string, translationVersion?: number): void {
    if (!this.draft) return;
    this.draft.locale = locale;
    this.draft.translation_version = translationVersion;
    this.retainedMetadata.locale = locale;
    this.retainedMetadata.translation_version = translationVersion;
  }
}
