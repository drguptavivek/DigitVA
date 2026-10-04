import type { WhoVaDraft, WhoVaDraftStore } from "@drguptavivek/who-2022-va";

import type { DefinitionPin } from "../formDefinitionRuntime";

type RevisionDraft = WhoVaDraft & {
  startedAt?: string;
  completedAt?: string;
  locale?: string;
  translation_version?: number;
  definitionSha256?: DefinitionPin["definitionSha256"];
  definitionExtensions?: DefinitionPin["definitionExtensions"];
};

/** Keep a submitted interview's editable copy in memory for this mounted screen only. */
export class RevisionMemoryStore implements WhoVaDraftStore {
  private draft: RevisionDraft | undefined;
  private readonly retainedMetadata: Pick<RevisionDraft,
    "instrumentVersion" | "startedAt" | "completedAt" | "locale" | "translation_version" | "definitionSha256" | "definitionExtensions">;

  constructor(draft: RevisionDraft) {
    this.draft = { ...draft };
    this.retainedMetadata = {
      instrumentVersion: draft.instrumentVersion,
      ...(draft.startedAt ? { startedAt: draft.startedAt } : {}),
      ...(draft.completedAt ? { completedAt: draft.completedAt } : {}),
      ...(draft.locale ? { locale: draft.locale } : {}),
      ...(draft.translation_version !== undefined ? { translation_version: draft.translation_version } : {}),
      ...(draft.definitionSha256 !== undefined ? { definitionSha256: draft.definitionSha256 } : {}),
      ...(draft.definitionExtensions !== undefined ? { definitionExtensions: [...draft.definitionExtensions] } : {})
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
