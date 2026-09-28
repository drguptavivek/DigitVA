/**
 * Custom-element wrapper that embeds the React web form in non-React pages and
 * exposes imperative data, validation, draft, and completion APIs.
 */
import React from "react";
import { createRoot, type Root } from "react-dom/client";

import { createDraftId } from "./draft.js";
import { createWhoVaSession } from "./engine/session.js";
import { whoVa2022Instrument } from "./instrument.js";
import { loadWhoVa2022Language } from "./instrument-loader.js";
import type {
  InstrumentDefinition,
  SubmissionData,
  SubmissionValidationResult,
  WhoVaDraftStore,
  WhoVaSession
} from "./types.js";
import type { WhoVaPlatformServices } from "./ui/create-who-va-form.js";
import { WhoVaForm } from "./web.js";

export class WhoVaFormElement extends HTMLElement {
  static get observedAttributes() {
    return [
      "auto-save-draft-interval-ms",
      "auto-save-draft-on-change",
      "draft-id",
      "hide-question-codes",
      "locale",
      "show-english",
      "show-guidance"
    ];
  }

  private root: Root | undefined;
  private session: WhoVaSession;
  /**
   * The instrument the current session was built from. `setInstrument` only
   * accepts a translation of the same semantic contract, so switching to a
   * different questionnaire needs a new session rather than a language swap.
   */
  private sessionBase: InstrumentDefinition;
  /**
   * Set once the first renderForm has built a session for sessionBase. Until
   * then, a matching id/version is not proof of a matching question set (see
   * renderForm), so the first render always starts a fresh session.
   */
  private sessionEstablished = false;
  private readonly generatedDraftId = createDraftId();
  private configuredDraftStore: WhoVaDraftStore | undefined;
  private configuredInstrument: InstrumentDefinition | undefined;
  private configuredPlatform: WhoVaPlatformServices | undefined;
  private configuredLockedQuestionNames: readonly string[] = [];
  private renderVersion = 0;
  /**
   * Bumped whenever a new session is created: the form keeps the session it
   * mounted with, so a new one needs a new mount, else `setData()` would
   * write to a session the page is not showing.
   */
  private sessionVersion = 0;

  constructor() {
    super();
    this.sessionBase = whoVa2022Instrument;
    this.session = createWhoVaSession(whoVa2022Instrument);
  }

  connectedCallback(): void {
    void this.renderForm();
  }

  disconnectedCallback(): void {
    this.root?.unmount();
    this.root = undefined;
  }

  attributeChangedCallback(): void {
    if (this.isConnected) void this.renderForm();
  }

  getData(): SubmissionData {
    return this.session.getSnapshot().data;
  }

  setData(data: SubmissionData): void {
    this.session.replaceData(data);
  }

  get lockedQuestionNames(): readonly string[] {
    return this.configuredLockedQuestionNames;
  }

  set lockedQuestionNames(names: Iterable<string> | undefined) {
    this.setLockedQuestionNames(names ?? []);
  }

  setLockedQuestionNames(names: Iterable<string>): void {
    this.configuredLockedQuestionNames = [...names];
    this.session.setLockedQuestionNames(this.configuredLockedQuestionNames);
    if (this.isConnected) void this.renderForm();
  }

  validate(): SubmissionValidationResult {
    return this.session.validate();
  }

  complete(): SubmissionValidationResult {
    return this.session.complete();
  }

  getDraftId(): string {
    return this.getAttribute("draft-id") ?? this.generatedDraftId;
  }

  private getAutoSaveDraftIntervalMs(): number | false | undefined {
    const value = this.getAttribute("auto-save-draft-interval-ms");
    if (value == null || value.trim() === "") return undefined;
    if (value === "false" || value === "off") return false;
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
  }

  /**
   * Host-provided durable storage. Assign this property before connecting the
   * element to enable draft persistence.
   */
  get draftStore(): WhoVaDraftStore | undefined {
    return this.configuredDraftStore;
  }

  set draftStore(store: WhoVaDraftStore | undefined) {
    if (store === this.configuredDraftStore) return;
    this.configuredDraftStore = store;
    if (this.isConnected) void this.renderForm();
  }

  /**
   * Render a questionnaire other than the built-in WHO 2022 instrument — for
   * example one DigitVA generated from an XLSForm. Assign before connecting.
   * Unset, the element loads the built-in instrument as before.
   *
   * Setting this disables the locale attribute's language loading, which only
   * knows about the built-in instrument's translations.
   */
  get instrument(): InstrumentDefinition | undefined {
    return this.configuredInstrument;
  }

  set instrument(instrument: InstrumentDefinition | undefined) {
    if (instrument === this.configuredInstrument) return;
    this.configuredInstrument = instrument;
    if (this.isConnected) void this.renderForm();
  }

  /** Identifies the rendered questionnaire: its host key, name and version. */
  get instrumentIdentity(): {
    formTypeCode?: string;
    id: string;
    title: string;
    version: string;
  } {
    const instrument = this.configuredInstrument ?? whoVa2022Instrument;
    return {
      ...(instrument.formTypeCode ? { formTypeCode: instrument.formTypeCode } : {}),
      id: instrument.id,
      title: instrument.title,
      version: instrument.version
    };
  }

  /** Host-controlled attachment, recording, picker, and lifecycle services. */
  get platform(): WhoVaPlatformServices | undefined {
    return this.configuredPlatform;
  }

  set platform(platform: WhoVaPlatformServices | undefined) {
    if (platform === this.configuredPlatform) return;
    this.configuredPlatform = platform;
    if (this.isConnected) void this.renderForm();
  }

  private async renderForm(): Promise<void> {
    const renderVersion = ++this.renderVersion;
    const requestedLocale = this.getAttribute("locale") ?? "en";
    // A host-supplied instrument is used as given: the language loader only
    // carries translations for the built-in WHO instrument.
    const language = this.configuredInstrument
      ? { instrument: this.configuredInstrument, locale: requestedLocale, uiTranslations: {} }
      : await loadWhoVa2022Language(requestedLocale);
    if (!this.isConnected || renderVersion !== this.renderVersion) return;
    const base = this.configuredInstrument ?? whoVa2022Instrument;
    // Same questionnaire (id + version) as a locale switch re-supplies: a
    // translated copy is a new object every time (see applyTranslations),
    // so comparing by reference treated every language switch as a new
    // questionnaire and dropped the session's answers (digitva-ybz). Only a
    // genuine contract change -- a different id or version -- starts fresh.
    // The very first render always starts fresh too: the constructor's
    // session was built from the full built-in instrument, which can have
    // the same id and version as a host's extension-filtered one (id and
    // version come from the generated JSON, not from which extensions are
    // enabled) while carrying a different question set -- reusing it would
    // hand setInstrument a real content change, which it rejects.
    const sameQuestionnaire =
      this.sessionEstablished && base.id === this.sessionBase.id && base.version === this.sessionBase.version;
    this.sessionBase = base;
    this.sessionEstablished = true;
    if (!sameQuestionnaire) {
      // A different questionnaire: start a session for it. Answers do not
      // carry across, which is the only safe reading of a contract change.
      this.session = createWhoVaSession(base);
      this.sessionVersion += 1;
      this.session.setLockedQuestionNames(this.configuredLockedQuestionNames);
    } else {
      this.session.setInstrument(language.instrument);
    }
    this.session.setLocale(language.locale, language.uiTranslations);
    const autoSaveDraftIntervalMs = this.getAutoSaveDraftIntervalMs();
    this.root ??= createRoot(this);
    this.root.render(
      <WhoVaForm
        key={`${this.getDraftId()}:${this.sessionVersion}`}
        instrument={language.instrument}
        session={this.session}
        draftId={this.getDraftId()}
        {...(this.configuredDraftStore ? { draftStore: this.configuredDraftStore } : {})}
        {...(this.configuredPlatform ? { platform: this.configuredPlatform } : {})}
        lockedQuestionNames={this.configuredLockedQuestionNames}
        locale={language.locale}
        uiTranslations={language.uiTranslations}
        showSourceGuidance={this.hasAttribute("show-guidance")}
        showEnglish={this.hasAttribute("show-english")}
        showQuestionCodes={!this.hasAttribute("hide-question-codes")}
        autoSaveDraftOnChange={this.hasAttribute("auto-save-draft-on-change")}
        {...(autoSaveDraftIntervalMs !== undefined ? { autoSaveDraftIntervalMs } : {})}
        onChange={(data) =>
          this.dispatchEvent(new CustomEvent("who-va-change", { detail: data, bubbles: true }))
        }
        onValidation={(issues) =>
          this.dispatchEvent(new CustomEvent("who-va-validation", { detail: issues, bubbles: true }))
        }
        onDraftSaved={(draft) =>
          this.dispatchEvent(new CustomEvent("who-va-draft-saved", { detail: draft, bubbles: true }))
        }
        onDraftError={(error) =>
          this.dispatchEvent(new CustomEvent("who-va-draft-error", { detail: error, bubbles: true }))
        }
        onDraftRestored={(result) =>
          this.dispatchEvent(new CustomEvent("who-va-ready", { detail: result, bubbles: true }))
        }
        onComplete={(result) =>
          this.dispatchEvent(new CustomEvent("who-va-complete", { detail: result, bubbles: true }))
        }
      />
    );
  }
}

export function defineWhoVaElement(tagName = "who-va-2022-form"): typeof WhoVaFormElement {
  const existing = customElements.get(tagName);
  if (existing) return existing as typeof WhoVaFormElement;
  const RegisteredWhoVaFormElement = class extends WhoVaFormElement {};
  customElements.define(tagName, RegisteredWhoVaFormElement);
  return RegisteredWhoVaFormElement;
}

export * from "./web.js";
