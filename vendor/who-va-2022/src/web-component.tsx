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
import type { SubmissionData, SubmissionValidationResult, WhoVaDraftStore, WhoVaSession } from "./types.js";
import type { WhoVaPlatformServices } from "./ui/create-who-va-form.js";
import { WhoVaForm } from "./web.js";

export class WhoVaFormElement extends HTMLElement {
  static get observedAttributes() {
    return [
      "auto-save-draft-interval-ms",
      "auto-save-draft-on-change",
      "draft-id",
      "locale",
      "show-guidance"
    ];
  }

  private root: Root | undefined;
  private readonly session: WhoVaSession;
  private readonly generatedDraftId = createDraftId();
  private configuredDraftStore: WhoVaDraftStore | undefined;
  private configuredPlatform: WhoVaPlatformServices | undefined;
  private configuredLockedQuestionNames: readonly string[] = [];
  private renderVersion = 0;

  constructor() {
    super();
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
    const language = await loadWhoVa2022Language(requestedLocale);
    if (!this.isConnected || renderVersion !== this.renderVersion) return;
    this.session.setInstrument(language.instrument);
    this.session.setLocale(language.locale, language.uiTranslations);
    const autoSaveDraftIntervalMs = this.getAutoSaveDraftIntervalMs();
    this.root ??= createRoot(this);
    this.root.render(
      <WhoVaForm
        key={this.getDraftId()}
        instrument={language.instrument}
        session={this.session}
        draftId={this.getDraftId()}
        {...(this.configuredDraftStore ? { draftStore: this.configuredDraftStore } : {})}
        {...(this.configuredPlatform ? { platform: this.configuredPlatform } : {})}
        lockedQuestionNames={this.configuredLockedQuestionNames}
        locale={language.locale}
        uiTranslations={language.uiTranslations}
        showSourceGuidance={this.hasAttribute("show-guidance")}
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
