import {
  createWhoVa2022Instrument,
  WHO_VA_FORM_VERSION,
  type SubmissionData,
  type InstrumentDefinition,
  type SubmissionValidationResult
} from "@drguptavivek/who-2022-va";
import { WhoVaForm, type WhoVaDraftController } from "@drguptavivek/who-2022-va/web";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { ClientApiError, getCaseDetail, getDraft, getInstrumentTranslations, getIntakeContext, getProjectFormOptions, requestRaw, startDraft, submitDraft, type DraftResponse, type FormOptions, type IntakeBootstrap } from "../client/api";
import { ServerDraftStore } from "../client/serverDraftStore";
import { RevisionMemoryStore } from "../client/revisionMemoryStore";
import { createRevisionSnapshot, getRevisionDetail, isPartialOutcome, postRevision, revisionOutcome, type RevisionDetail, type RevisionReasonCode, type RevisionSnapshot } from "../client/revisions";
import { resolveNewInterviewDefinition, resolveSavedEnvelopeDefinition, withDefinitionPin, type DefinitionCache, type DefinitionPin, type ResolvedInstrument } from "../formDefinitionRuntime";
import type { DefinitionRequest } from "../formDefinitions";
import type { Prefill } from "../cases";
import { initialDataFromPrefill } from "../prefill";
import { useAppState } from "../AppState";
import { questionnaireDefault, questionnaireLocales, t, type StringKey } from "../i18n";
import { useTheme } from "../theme";
import { applyTranslations } from "../translations";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";

function instrumentCode(options: FormOptions): string {
  const code = options.form_types?.find((formType) => formType.is_default)?.instrument_code;
  if (code !== "WHO_2022_VA") throw new Error("unsupported_instrument");
  return code;
}

function narrationLanguageCodes(options: FormOptions): string[] {
  return (options.narration_languages ?? []).map((language) => language.code);
}

function definitionOptions(options: FormOptions) {
  return {
    instrumentVersion: options.instrument_version ?? null,
    definitionSha256: options.definition_sha256 ?? null,
    extensions: options.enabled_extensions ?? [],
  };
}

function definitionRequest(
  csrf: { header: string; token: string },
  isCurrent: () => boolean,
): DefinitionRequest {
  return async (path, options) => {
    if (!isCurrent()) throw new Error("request_superseded");
    const response = await requestRaw("", path, { csrf, ...options });
    if (!isCurrent()) throw new Error("request_superseded");
    return response;
  };
}

function sameDefinitionPin(left: DefinitionPin | null, right: DefinitionPin | null): boolean {
  return left === right || (!!left && !!right &&
    left.instrumentVersion === right.instrumentVersion &&
    left.definitionSha256 === right.definitionSha256 &&
    left.definitionExtensions.length === right.definitionExtensions.length &&
    left.definitionExtensions.every((extension, index) => extension === right.definitionExtensions[index]));
}

interface BrowserDefinitionAccess {
  definitionCache?: DefinitionCache;
  hasServedDefinition(projectId: string): boolean;
  markServedDefinition(projectId: string): Promise<void>;
  sessionGeneration: number;
}

/** Keep the server's actionable stale-draft explanation visible to the interviewer. */
function interviewErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.code === "draft_stale") {
    const message = error.payload?.error;
    if (typeof message === "string" && message.trim()) return message.trim().slice(0, 500);
  }
  return browserErrorText(error);
}

function revisionErrorText(error: unknown): string {
  if (!(error instanceof ClientApiError)) return browserErrorText(error);
  const errorKeys: Record<string, StringKey> = {
    not_found: "revisionUnavailable",
    revision_locked: "revisionLocked",
    case_state_conflict: "revisionCaseConflict",
    case_closed: "revisionCaseClosed",
    case_already_submitted: "revisionAlreadySubmitted",
    invalid_reason: "revisionInvalidReason",
    answers_hash_required: "serverValidation",
    answers_hash_invalid: "serverValidation",
    invalid_interview: "serverValidation"
  };
  const key = errorKeys[error.code ?? ""];
  return key ? t(key) : browserErrorText(error);
}

/** Normalize legacy empty identity placeholders and reject a different composed instrument before the form mounts. */
export function normalizeRevisionEnvelope(
  envelope: RevisionDetail["envelope"],
  instrument: InstrumentDefinition
): RevisionDetail["envelope"] {
  if (
    (envelope.formVersion && envelope.formVersion !== WHO_VA_FORM_VERSION) ||
    (envelope.instrumentId && envelope.instrumentId !== instrument.id) ||
    (envelope.instrumentVersion && envelope.instrumentVersion !== instrument.version)
  ) {
    throw new Error("revision_instrument_mismatch");
  }
  return {
    ...envelope,
    formVersion: envelope.formVersion || WHO_VA_FORM_VERSION,
    instrumentId: envelope.instrumentId || instrument.id,
    instrumentVersion: envelope.instrumentVersion || instrument.version,
  };
}

export default function InterviewScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{
    draftId?: string;
    revisionDraftId?: string;
    revisionProjectId?: string;
    revisionSiteId?: string;
    revisionVaSid?: string;
    deathId?: string;
    projectId?: string;
    siteId?: string;
    orgUnitId?: string;
  }>();
  const appState = useAppState();
  const { bootstrap, chooseUiLocale } = appState;
  const { definitionCache, hasServedDefinition, markServedDefinition, sessionGeneration } =
    appState as typeof appState & BrowserDefinitionAccess;
  const styles = useUiStyles();
  const theme = useTheme();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [draftId, setDraftId] = useState(params.draftId);
  const [draft, setDraft] = useState<DraftResponse>();
  const [revision, setRevision] = useState<RevisionDetail>();
  const [instrument, setInstrument] = useState<InstrumentDefinition>();
  const [resolvedInstrument, setResolvedInstrument] = useState<ResolvedInstrument>();
  const [locale, setLocale] = useState("en");
  const [locales, setLocales] = useState<FormOptions["available_locales"]>([]);
  const [store, setStore] = useState<ServerDraftStore | RevisionMemoryStore>();
  const [controller, setController] = useState<WhoVaDraftController>();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [translationFallback, setTranslationFallback] = useState(false);
  const [message, setMessage] = useState("");
  const [revisionReason, setRevisionReason] = useState<RevisionReasonCode>();
  const [needsNewSnapshot, setNeedsNewSnapshot] = useState(false);
  const [loadedBootstrap, setLoadedBootstrap] = useState(bootstrap);
  const bootstrapRef = useRef(bootstrap);
  const generationRef = useRef(0);
  const initializationGenerationRef = useRef(0);
  const revisionGenerationRef = useRef(0);
  const pendingRevisionRef = useRef<RevisionSnapshot | undefined>(undefined);
  if (bootstrapRef.current !== bootstrap) {
    bootstrapRef.current = bootstrap;
    generationRef.current += 1;
    pendingRevisionRef.current = undefined;
  }
  const draftPrefill = draft?.prefill as Prefill | undefined;

  const initialise = useCallback(async (isInitializationActive: () => boolean) => {
    if (!bootstrap || !definitionCache) return;
    const currentDefinitionCache: DefinitionCache = definitionCache;
    const generation = generationRef.current;
    const requestSessionGeneration = sessionGeneration;
    const isCurrent = () => isInitializationActive() && generationRef.current === generation &&
      bootstrapRef.current === bootstrap && requestSessionGeneration === sessionGeneration;
    if (!isCurrent()) return;
    setLoadedBootstrap(undefined);
    const nextIntake = await getIntakeContext(bootstrap.csrf);
    if (!isCurrent()) return;
    setIntake(nextIntake);
    let nextDraftId = params.draftId;
    let nextRevision: RevisionDetail | undefined;
    let options: FormOptions | undefined;
    let resolved: ResolvedInstrument | undefined;
    const request = definitionRequest(bootstrap.csrf, isCurrent);
    const accountId = bootstrap.user.user_id;

    async function resolveNew(projectId: string, formOptions: FormOptions): Promise<ResolvedInstrument> {
      instrumentCode(formOptions);
      const bundled = createWhoVa2022Instrument(formOptions.enabled_extensions ?? []);
      return resolveNewInterviewDefinition({
        accountId,
        projectId,
        options: definitionOptions(formOptions),
        request,
        cache: currentDefinitionCache,
        narrationLanguageCodes: narrationLanguageCodes(formOptions),
        bundledOriginal: {
          instrument: bundled,
          instrumentVersion: bundled.version,
          extensions: formOptions.enabled_extensions ?? [],
        },
        canUseBundledFallback: async () => isCurrent() && !hasServedDefinition(projectId),
        onServedDefinition: async () => {
          if (!isCurrent()) throw new Error("request_superseded");
          await markServedDefinition(projectId);
          if (!isCurrent()) throw new Error("request_superseded");
        },
      });
    }

    if (params.revisionDraftId) {
      if (!params.revisionProjectId || !params.revisionSiteId || !params.revisionVaSid) {
        throw new ClientApiError(400, "malformed_response");
      }
      nextRevision = await getRevisionDetail(bootstrap.links.intakeDrafts, params.revisionDraftId, bootstrap.csrf, {
        draft_id: params.revisionDraftId,
        project_id: params.revisionProjectId,
        site_id: params.revisionSiteId,
        va_sid: params.revisionVaSid,
      });
      if (!isCurrent()) return;
      nextDraftId = nextRevision.draft.draft_id;
      setDraftId(nextDraftId);
    }
    if (!nextDraftId && params.deathId) {
      const { case: caseRow } = await getCaseDetail(bootstrap.links.intakeCases, params.deathId, bootstrap.csrf);
      if (!isCurrent()) return;
      if (!caseRow?.prefill) throw new Error("caseActionsUnavailable");
      if (!caseRow.project_id || !caseRow.site_id) throw new Error("case_context_missing");
      if (caseRow.my_draft_id) {
        nextDraftId = caseRow.my_draft_id;
        setDraftId(nextDraftId);
      } else {
        options = await getProjectFormOptions(caseRow.project_id, bootstrap.csrf);
        if (!isCurrent()) return;
        resolved = await resolveNew(caseRow.project_id, options);
        if (!isCurrent()) return;
        const started = await startDraft(
          bootstrap.links.intakeDrafts,
          {
            project_id: caseRow.project_id,
            site_id: caseRow.site_id,
            ...(caseRow.org_unit_id ? { org_unit_id: caseRow.org_unit_id } : {}),
            death_id: params.deathId
          },
          bootstrap.csrf
        );
        if (!isCurrent()) return;
        nextDraftId = started.draft.draft_id;
        setDraftId(nextDraftId);
      }
    }
    if (!nextDraftId && !params.deathId && params.projectId && params.siteId) {
      const context = nextIntake.context.find((entry) => entry.project_id === params.projectId && entry.site_id === params.siteId);
      if (!context || !["direct", "both"].includes(context.web_intake_mode ?? "")) throw new Error("intake_configuration_unavailable");
      options = await getProjectFormOptions(params.projectId, bootstrap.csrf);
      if (!isCurrent()) return;
      resolved = await resolveNew(params.projectId, options);
      if (!isCurrent()) return;
      const started = await startDraft(
        bootstrap.links.intakeDrafts,
        {
          project_id: params.projectId,
          site_id: params.siteId,
          ...(params.orgUnitId ? { org_unit_id: params.orgUnitId } : {})
        },
        bootstrap.csrf
      );
      if (!isCurrent()) return;
      nextDraftId = started.draft.draft_id;
      setDraftId(nextDraftId);
    }
    if (!nextDraftId) throw new Error("draft_missing");
    const nextDraft = nextRevision ?? await getDraft(bootstrap.links.intakeDrafts, nextDraftId, bootstrap.csrf);
    if (!isCurrent()) return;
    options ??= await getProjectFormOptions(nextDraft.draft.project_id, bootstrap.csrf);
    if (!isCurrent()) return;
    instrumentCode(options);
    resolved ??= await resolveSavedEnvelopeDefinition({
      accountId: bootstrap.user.user_id,
      projectId: nextDraft.draft.project_id,
      envelope: nextDraft.envelope,
      request,
      cache: currentDefinitionCache,
      narrationLanguageCodes: narrationLanguageCodes(options),
      bundledLegacyDefinitions: [],
    });
    if (!isCurrent()) return;
    const base = resolved.instrument;
    const normalizedRevision = nextRevision
      ? {
          ...nextRevision,
          envelope: withDefinitionPin(normalizeRevisionEnvelope(nextRevision.envelope, base), resolved.pin),
        }
      : undefined;
    const savedLocale = nextDraft.envelope.locale;
    const nextLocale = savedLocale ?? questionnaireDefault(options.available_locales, options.default_locale);
    const translated = await translatedResolvedInstrument(resolved, nextLocale, options, bootstrap.csrf);
    if (!isCurrent()) return;
    const nextInstrument = translated.instrument;
    setTranslationFallback(translated.fallback);
    await chooseUiLocale(nextLocale);
    if (!isCurrent()) return;
    const sectionOf = new Map(base.questions.map((question) => [question.name, question.sectionPath.at(-1) ?? "_root"]));
    const prefill = nextDraft.prefill as Prefill;
    const prefillData = initialDataFromPrefill(prefill) as SubmissionData;
    const initialData = normalizedRevision
      ? { ...prefillData, ...normalizedRevision.envelope.data }
      : prefillData;
    const nextStore = normalizedRevision
      ? new RevisionMemoryStore({ ...normalizedRevision.envelope, data: initialData })
      : new ServerDraftStore({
          endpoint: bootstrap.links.intakeDrafts,
          csrf: bootstrap.csrf,
          sectionOf,
          initialData,
          definitionPin: resolved.pin,
          identity: {
            instrumentId: nextInstrument.id,
            instrumentVersion: resolved.pin?.instrumentVersion ?? nextInstrument.version,
            firstSection: nextInstrument.sections[0]?.name ?? ""
          },
          locale: nextLocale,
          translationVersion: nextDraft.envelope.translation_version ?? options.translation_versions?.[nextLocale] ?? 0,
          onError: (error) => { if (isCurrent()) setMessage(interviewErrorText(error)); }
        });
    if (nextStore instanceof ServerDraftStore) await nextStore.load(nextDraftId);
    if (!isCurrent()) return;
    setDraft(nextDraft);
    setRevision(normalizedRevision);
    setLocale(nextLocale);
    setLocales(questionnaireLocales(options.available_locales));
    setResolvedInstrument(resolved);
    setInstrument(nextInstrument);
    setStore(nextStore);
    setLoadedBootstrap(bootstrap);
  }, [bootstrap, chooseUiLocale, definitionCache, hasServedDefinition, markServedDefinition, params.deathId, params.draftId, params.orgUnitId, params.projectId, params.revisionDraftId, params.revisionProjectId, params.revisionSiteId, params.revisionVaSid, params.siteId, sessionGeneration]);

  useEffect(() => {
    setIntake(undefined);
    setDraftId(params.draftId);
    setDraft(undefined);
    setRevision(undefined);
    setInstrument(undefined);
    setResolvedInstrument(undefined);
    setStore(undefined);
    setController(undefined);
    setDirty(false);
    setRevisionReason(undefined);
    setNeedsNewSnapshot(false);
    setMessage("");
    setLoadedBootstrap(undefined);
    revisionGenerationRef.current = 0;
    pendingRevisionRef.current = undefined;
  }, [bootstrap, params.deathId, params.draftId, params.orgUnitId, params.projectId, params.revisionDraftId, params.revisionProjectId, params.revisionSiteId, params.revisionVaSid, params.siteId, sessionGeneration]);

  useEffect(() => {
    let active = true;
    const requestBootstrap = bootstrap;
    const initializationGeneration = ++initializationGenerationRef.current;
    const isCurrent = () => active && initializationGenerationRef.current === initializationGeneration && bootstrapRef.current === requestBootstrap;
    void initialise(isCurrent).catch((error) => {
      if (!isCurrent()) return;
      if (error instanceof ClientApiError && [401, 403].includes(error.status)) {
        setInstrument(undefined);
        setStore(undefined);
      }
      setMessage(params.revisionDraftId ? revisionErrorText(error) : interviewErrorText(error));
    });
    return () => { active = false; };
  }, [bootstrap, initialise, params.revisionDraftId, sessionGeneration]);

  // Browser navigation warns before losing a revision held only in memory.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
      void controller?.saveDraft().then(() => store instanceof ServerDraftStore ? store.flush() : undefined).catch(() => undefined);
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [controller, dirty, store]);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return undefined;
    const style = document.createElement("style");
    style.textContent = `
      #digitva-who-form-theme [stroke="#004687"] {
        stroke: var(--who-2022-web-color-brand-deep) !important;
      }
      #digitva-who-form-theme [stroke="#ffffff"],
      #digitva-who-form-theme [stroke="#fff"] {
        stroke: var(--who-2022-web-color-on-accent, #ffffff) !important;
      }
    `;
    document.head.appendChild(style);
    return () => style.remove();
  }, []);

  const switchLocale = useCallback(async (nextLocale: string): Promise<boolean> => {
    if (!bootstrap || !intake || !draft || !instrument || !resolvedInstrument || !store) return false;
    const generation = generationRef.current;
    const isCurrent = () => generationRef.current === generation && bootstrapRef.current === bootstrap;
    setBusy(true);
    setMessage("");
    const previousMetadata = store instanceof ServerDraftStore ? store.getLocaleMetadata() : undefined;
    try {
      if (nextLocale === locale) {
        await chooseUiLocale(nextLocale);
        return true;
      }
      await controller?.saveDraft();
      if (store instanceof ServerDraftStore) await store.flush();
      const options = await getProjectFormOptions(draft.draft.project_id, bootstrap.csrf);
      if (!isCurrent()) return false;
      const next = await translatedResolvedInstrument(resolvedInstrument, nextLocale, options, bootstrap.csrf);
      if (!isCurrent()) return false;
      const translationVersion = options.translation_versions?.[nextLocale] ?? 0;
      store.setLocaleMetadata(nextLocale, translationVersion);
      // Keep the selected locale with the mounted revision and preserve the
      // existing server-save behavior for an ordinary draft.
      await controller?.saveDraft();
      if (store instanceof ServerDraftStore) await store.flush();
      if (!isCurrent()) return false;
      await chooseUiLocale(nextLocale);
      if (!isCurrent()) return false;
      setInstrument(next.instrument);
      setTranslationFallback(next.fallback);
      setLocale(nextLocale);
      return true;
    } catch (error) {
      if (store instanceof ServerDraftStore && previousMetadata) store.restoreLocaleMetadata(previousMetadata);
      if (error instanceof ClientApiError && [401, 403].includes(error.status)) {
        setInstrument(undefined);
        setStore(undefined);
      }
      if (isCurrent()) setMessage(browserErrorText(error));
      return false;
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }, [bootstrap, chooseUiLocale, controller, draft, instrument, intake, locale, resolvedInstrument, store]);

  async function sendRevisionSnapshot(snapshot: RevisionSnapshot) {
    if (!bootstrap) return;
    const accountGeneration = generationRef.current;
    const isCurrent = () => generationRef.current === accountGeneration && bootstrapRef.current === bootstrap;
    setBusy(true);
    try {
      const acknowledgement = await postRevision(bootstrap.csrf, snapshot);
      if (!isCurrent() || pendingRevisionRef.current !== snapshot) return;
      pendingRevisionRef.current = undefined;
      setRevision((current) => current ? {
        ...current,
        answers_sha256: acknowledgement.answers_sha256,
        envelope: {
          ...current.envelope,
          data: { ...current.envelope.data, interview_outcome: acknowledgement.outcome },
        },
      } : current);
      if (revisionReason === "finish_partial" && !isPartialOutcome(acknowledgement.outcome)) {
        setRevisionReason(undefined);
      }
      if (revisionGenerationRef.current === snapshot.generation) {
        setDirty(false);
        router.replace("/collection");
      } else {
        setDirty(true);
        setMessage(acknowledgement.changed ? t("revisionSaved") : t("revisionNoCodingChange"));
      }
    } catch (error) {
      if (isCurrent() && error instanceof ClientApiError && [404, 409, 422].includes(error.status)) {
        pendingRevisionRef.current = undefined;
        setNeedsNewSnapshot(true);
      }
      if (isCurrent()) setMessage(revisionErrorText(error));
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }

  async function complete(result: SubmissionValidationResult) {
    if (!bootstrap || !draftId || !store) return;
    const accountGeneration = generationRef.current;
    const isCurrent = () => generationRef.current === accountGeneration && bootstrapRef.current === bootstrap;
    setBusy(true);
    setMessage("");
    try {
      try {
        await controller?.saveDraft();
        if (!isCurrent()) return;
        if (store instanceof ServerDraftStore) await store.flush();
      } catch (error) {
        if (!isCurrent()) return;
        if (!(store instanceof ServerDraftStore) || !(error instanceof ClientApiError) || error.status !== 409) throw error;
        const currentDraft = await getDraft(bootstrap.links.intakeDrafts, draftId, bootstrap.csrf);
        if (!isCurrent()) return;
        if (currentDraft.draft.status !== "submitted") throw error;
      }
      if (!isCurrent()) return;
      if (store instanceof RevisionMemoryStore) {
        let snapshot = pendingRevisionRef.current;
        if (!snapshot) {
          if (!revision || !revisionReason) {
            setMessage(t("revisionInvalidReason"));
            return;
          }
          const current = store.getCurrent();
          if (!current) throw new ClientApiError(404, "not_found");
          const wasPartial = isPartialOutcome(revision.envelope.data.interview_outcome);
          const nextOutcome = revisionOutcome(current.data, result.valid);
          if (!nextOutcome) {
            setMessage(result.valid ? t("revisionConsentRequired") : t("serverValidation"));
            return;
          }
          if ((wasPartial && nextOutcome === "completed" && revisionReason !== "finish_partial") ||
              (revisionReason === "finish_partial" && (!wasPartial || nextOutcome !== "completed"))) {
            setMessage(t("revisionInvalidReason"));
            return;
          }
          snapshot = await createRevisionSnapshot({
            vaSid: revision.draft.va_sid,
            reasonCode: revisionReason,
            data: current.data,
            completion: { valid: result.valid, issues: result.issues },
            draft: {
              ...(current.startedAt ? { startedAt: current.startedAt } : {}),
              instrumentVersion: current.instrumentVersion,
              ...(current.definitionSha256 ? { definitionSha256: current.definitionSha256 } : {}),
              ...(current.definitionExtensions ? { definitionExtensions: current.definitionExtensions } : {}),
            },
            generation: revisionGenerationRef.current,
          });
          if (!isCurrent()) return;
          pendingRevisionRef.current = snapshot;
          setNeedsNewSnapshot(false);
        }
        await sendRevisionSnapshot(snapshot);
        return;
      }
      const submission = await submitDraft(
        bootstrap.links.intakeDrafts,
        draftId,
        { valid: result.valid, issues: result.issues, data: result.data },
        bootstrap.csrf,
        store instanceof ServerDraftStore ? store.getServerUpdatedAt() : undefined,
      );
      if (!isCurrent()) return;
      if (submission.superseded) {
        router.replace({ pathname: "/collection", params: { superseded: "1" } });
      } else if (submission.kept === "server") {
        router.replace({ pathname: "/collection", params: {
          submissionHistory: "1",
          submissionLocked: submission.locked === true ? "1" : "0",
          ...(submission.can_code_now === true ? { canCodeNow: "1" } : {}),
          ...(submission.can_code_now === true && submission.draft.unique_id ? { readyUniqueId: submission.draft.unique_id } : {}),
        } });
      } else if (submission.can_code_now === true) {
        router.replace({ pathname: "/collection", params: {
          canCodeNow: "1",
          ...(submission.draft.unique_id ? { readyUniqueId: submission.draft.unique_id } : {}),
        } });
      } else {
        router.replace("/collection");
      }
    } catch (error) {
      if (isCurrent()) setMessage(store instanceof RevisionMemoryStore ? revisionErrorText(error) : interviewErrorText(error));
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }

  async function leave() {
    const requestBootstrap = bootstrap;
    const generation = generationRef.current;
    const isCurrent = () => bootstrapRef.current === requestBootstrap && generationRef.current === generation;
    try {
      await controller?.saveDraft();
      if (!isCurrent()) return;
      if (store instanceof RevisionMemoryStore && dirty) {
        setMessage(t("revisionUnsavedWarning"));
        return;
      }
      if (store instanceof ServerDraftStore) await store.flush();
      if (!isCurrent()) return;
      router.back();
    } catch (error) {
      if (isCurrent()) setMessage(store instanceof RevisionMemoryStore ? revisionErrorText(error) : interviewErrorText(error));
    }
  }

  const beforeNavigate = useCallback(async () => {
    const requestBootstrap = bootstrap;
    const generation = generationRef.current;
    const isCurrent = () => bootstrapRef.current === requestBootstrap && generationRef.current === generation;
    try {
      await controller?.saveDraft();
      if (!isCurrent()) return false;
      if (store instanceof RevisionMemoryStore && dirty) {
        setMessage(t("revisionUnsavedWarning"));
        return false;
      }
      if (store instanceof ServerDraftStore) await store.flush();
      if (!isCurrent()) return false;
      return true;
    } catch (error) {
      if (isCurrent()) setMessage(store instanceof RevisionMemoryStore ? revisionErrorText(error) : interviewErrorText(error));
      return false;
    }
  }, [bootstrap, controller, dirty, store]);

  const localeLabel = useMemo(() => locales?.find((entry) => entry.code === locale)?.label ?? locale, [locale, locales]);
  const availableLocales = locales ?? [];
  const webFormStyle = Platform.OS === "web"
    ? ({
        "--who-2022-web-color-brand": theme.colors.accent,
        "--who-2022-web-color-brand-deep": theme.colors.accentPressed,
        "--who-2022-web-color-brand-soft": theme.colors.accentSoft,
        "--who-2022-web-color-on-accent": theme.colors.onAccent,
        "--who-2022-web-color-canvas": theme.colors.background,
        "--who-2022-web-color-surface": theme.colors.surface,
        "--who-2022-web-color-ink": theme.colors.text,
        "--who-2022-web-color-muted": theme.colors.textMuted,
        "--who-2022-web-color-border": theme.colors.border,
        "--who-2022-web-color-control-border": theme.colors.border,
        "--who-2022-web-color-ink-subtle": theme.colors.textMuted,
        "--who-2022-web-color-guidance": theme.colors.warning,
        "--who-2022-web-color-danger": theme.colors.danger,
        "--who-2022-web-color-danger-border": theme.colors.danger,
        "--who-2022-web-color-danger-strong": theme.colors.danger,
        "--who-2022-web-color-danger-soft": theme.colors.dangerSoft,
        "--who-2022-web-color-image-background": theme.colors.surfaceMuted,
        "--who-2022-web-radius-control": "12px",
        "--who-2022-web-radius-card": "16px",
        "--who-2022-web-form-max-width": "48rem",
        "--who-2022-web-form-padding": "16px",
        "--who-2022-web-sticky-top": "0px"
      } as unknown as ViewStyle)
    : undefined;

  return (
    <WebShell
      title={t(revision ? "revisionTitle" : "interviewTitle")}
      beforeNavigate={beforeNavigate}
      headerAction={availableLocales.length ? (
        <QuestionnaireLanguageMenu
          locales={availableLocales}
          locale={locale}
          localeLabel={localeLabel}
          busy={busy}
          onSelect={switchLocale}
        />
      ) : null}
    >
      {loadedBootstrap === bootstrap && instrument && store && draftId ? (
        <>
          <View style={styles.row}>
            <Button kind="secondary" label={t("backToCollection")} onPress={() => void leave()} />
            {store instanceof ServerDraftStore ? (
              <Button loading={busy} kind="secondary" label={t("save")} onPress={() => void store.flush().catch((error) => setMessage(browserErrorText(error)))} />
            ) : null}
          </View>
          {revision ? (
            <View>
              <Text style={styles.headline}>{t("revisionReason")}</Text>
              {([
                ["interviewer_correction", "revisionReasonInterviewerCorrection", "revisionReasonMessageInterviewerCorrection"],
                ["respondent_correction", "revisionReasonRespondentCorrection", "revisionReasonMessageRespondentCorrection"],
                ["more_information", "revisionReasonMoreInformation", "revisionReasonMessageMoreInformation"],
                ...(isPartialOutcome(revision.envelope.data.interview_outcome)
                  ? [["finish_partial", "revisionReasonFinishPartial", "revisionReasonMessageFinishPartial"]]
                  : [])
              ] as Array<[RevisionReasonCode, StringKey, StringKey]>).map(([code, labelKey]) => (
                <Button
                  key={code}
                  kind="secondary"
                  label={`${t(labelKey)}${revisionReason === code ? " ✓" : ""}`}
                  onPress={() => {
                    if (!pendingRevisionRef.current && !busy) {
                      setRevisionReason(code);
                      setNeedsNewSnapshot(false);
                    }
                  }}
                />
              ))}
              {revisionReason ? (
                <Text style={styles.muted}>
                  {t(({
                    interviewer_correction: "revisionReasonMessageInterviewerCorrection",
                    respondent_correction: "revisionReasonMessageRespondentCorrection",
                    more_information: "revisionReasonMessageMoreInformation",
                    finish_partial: "revisionReasonMessageFinishPartial"
                  } as const)[revisionReason])}
                </Text>
              ) : null}
              {pendingRevisionRef.current ? (
                <Button
                  kind="secondary"
                  loading={busy}
                  label={t("revisionRetry")}
                  onPress={() => { const snapshot = pendingRevisionRef.current; if (snapshot && !busy) void sendRevisionSnapshot(snapshot); }}
                />
              ) : null}
              {needsNewSnapshot ? <Text style={styles.muted}>{t("revisionNewSnapshot")}</Text> : null}
            </View>
          ) : null}
          {translationFallback ? <Text style={styles.muted}>{t("questionnaireEnglishFallback")}</Text> : null}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          <View nativeID="digitva-who-form-theme" style={[{ minWidth: 0, width: "100%" }, webFormStyle]}>
            <WhoVaForm
              key={`${draftId}:${locale}`}
              instrument={instrument}
              locale={locale}
              showEnglish={locale !== "en"}
              draftId={draftId}
              draftStore={store}
              autoSaveDraftOnChange
              onDraftController={setController}
              onChange={() => {
                if (store instanceof RevisionMemoryStore) revisionGenerationRef.current += 1;
                setNeedsNewSnapshot(false);
                setDirty(true);
              }}
              onDraftSaved={() => { if (store instanceof ServerDraftStore) setDirty(false); }}
              onDraftError={(error) => setMessage(revision ? revisionErrorText(error) : browserErrorText(error))}
              onComplete={(result) => void complete(result)}
              lockedQuestionNames={draftPrefill?.lockedQuestionNames}
              portalThemeStyle={webFormStyle}
            />
          </View>
        </>
      ) : (
        <Text style={styles.muted}>{message || t("loading")}</Text>
      )}
    </WebShell>
  );
}

type QuestionnaireLocale = NonNullable<FormOptions["available_locales"]>[number];

function QuestionnaireLanguageMenu({
  locales,
  locale,
  localeLabel,
  busy,
  onSelect
}: {
  locales: QuestionnaireLocale[];
  locale: string;
  localeLabel: string;
  busy: boolean;
  onSelect: (nextLocale: string) => Promise<boolean>;
}) {
  const theme = useTheme();
  const [open, setOpen] = useState(false);
  const wasOpen = useRef(false);

  useEffect(() => {
    if (wasOpen.current && !open && typeof document !== "undefined") {
      document.getElementById("questionnaire-language-trigger")?.focus();
    }
    wasOpen.current = open;
  }, [open]);

  useEffect(() => {
    if (!open || typeof document === "undefined") return undefined;
    const closeOnEscapeOrOutside = (event: KeyboardEvent | PointerEvent) => {
      if (event instanceof KeyboardEvent) {
        if (event.key === "Escape") setOpen(false);
        return;
      }
      const root = document.getElementById("questionnaire-language-menu");
      if (root && event.target instanceof Node && !root.contains(event.target)) setOpen(false);
    };
    document.addEventListener("keydown", closeOnEscapeOrOutside);
    document.addEventListener("pointerdown", closeOnEscapeOrOutside);
    return () => {
      document.removeEventListener("keydown", closeOnEscapeOrOutside);
      document.removeEventListener("pointerdown", closeOnEscapeOrOutside);
    };
  }, [open]);

  async function selectLocale(nextLocale: string) {
    if (!(await onSelect(nextLocale))) return;
    setOpen(false);
  }

  return (
    <View nativeID="questionnaire-language-menu" style={languageStyles.anchor}>
      <Pressable
        nativeID="questionnaire-language-trigger"
        accessibilityRole="button"
        accessibilityLabel={t("formLanguage")}
        accessibilityHint={localeLabel}
        accessibilityState={{ expanded: open, busy }}
        aria-expanded={open}
        disabled={busy}
        onPress={() => setOpen((current) => !current)}
        style={({ pressed }) => [
          languageStyles.trigger,
          { backgroundColor: theme.colors.surface, borderColor: theme.colors.border, opacity: busy ? 0.5 : pressed ? 0.78 : 1 }
        ]}
      >
        <Text style={[languageStyles.triggerText, { color: theme.colors.text }]}>文A</Text>
      </Pressable>
      {open ? (
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel={t("formLanguage")}
          style={[languageStyles.popover, { backgroundColor: theme.colors.surface, borderColor: theme.colors.border }]}
        >
          {locales.map((entry) => {
            const selected = entry.code === locale;
            return (
              <Pressable
                key={entry.code}
                accessibilityRole="radio"
                accessibilityLabel={entry.label}
                accessibilityState={{ checked: selected, disabled: busy }}
                aria-checked={selected}
                disabled={busy}
                onPress={() => void selectLocale(entry.code)}
                style={({ pressed }) => [
                  languageStyles.option,
                  { backgroundColor: selected ? theme.colors.accentSoft : "transparent", opacity: pressed ? 0.78 : 1 }
                ]}
              >
                <Text style={[languageStyles.optionLabel, { color: theme.colors.text }]}>{entry.label}</Text>
                <Text style={[languageStyles.check, { color: theme.colors.accent }]}>{selected ? "✓" : ""}</Text>
              </Pressable>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

/** Missing or unreachable translations render English; other failures propagate. */
async function translatedResolvedInstrument(
  resolved: ResolvedInstrument,
  locale: string,
  options: FormOptions,
  csrf: { header: string; token: string },
): Promise<{ instrument: InstrumentDefinition; fallback: boolean }> {
  if (!locale || locale === "en") return { instrument: resolved.instrument, fallback: false };
  const pin = resolved.pin;
  const extensions = [...(options.enabled_extensions ?? [])].sort();
  if (
    !pin ||
    pin.instrumentVersion !== options.instrument_version ||
    pin.definitionSha256 !== options.definition_sha256 ||
    pin.definitionExtensions.length !== extensions.length ||
    pin.definitionExtensions.some((extension, index) => extension !== extensions[index])
  ) {
    return { instrument: resolved.instrument, fallback: true };
  }
  return translatedInstrument(resolved.instrument, locale, options, csrf);
}

async function translatedInstrument(
  base: InstrumentDefinition,
  locale: string,
  options: FormOptions,
  csrf: { header: string; token: string }
): Promise<{ instrument: InstrumentDefinition; fallback: boolean }> {
  const code = instrumentCode(options);
  if (!locale || locale === "en") return { instrument: base, fallback: false };
  try {
    const response = await getInstrumentTranslations(code, locale, csrf);
    return { instrument: applyTranslations(base, response, locale), fallback: !response };
  } catch (error) {
    if (error instanceof ClientApiError) {
      if (error.status === 404) return { instrument: base, fallback: true };
      throw error;
    }
    if (error instanceof TypeError) return { instrument: base, fallback: true };
    throw error;
  }
}

const languageStyles = StyleSheet.create({
  anchor: { position: "relative", zIndex: 20 },
  trigger: { minWidth: 48, minHeight: 48, borderWidth: 1, borderRadius: 12, alignItems: "center", justifyContent: "center" },
  triggerText: { fontSize: 17, fontWeight: "700" },
  popover: { position: "absolute", right: 0, top: 56, minWidth: 192, padding: 8, borderWidth: 1, borderRadius: 12, gap: 4, zIndex: 21, shadowColor: "#000", shadowOpacity: 0.16, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 4 },
  option: { minHeight: 48, borderRadius: 8, paddingHorizontal: 12, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16 },
  optionLabel: { fontSize: 16, lineHeight: 22, flexShrink: 1 },
  check: { width: 20, fontSize: 18, fontWeight: "700", textAlign: "center" }
});
