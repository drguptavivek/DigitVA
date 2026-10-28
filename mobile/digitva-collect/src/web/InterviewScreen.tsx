import type {
  SubmissionData,
  InstrumentDefinition,
  SubmissionValidationResult
} from "@drguptavivek/who-2022-va";
import type { WhoVaDraftController } from "@drguptavivek/who-2022-va/web";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { isTrainingProject, TRAINING_INTERVIEW_HOME } from "../training";
import { ClientApiError, getCaseDetail, getDraft, getInstrumentTranslations, getIntakeContext, getProjectFormOptions, requestClientJson, requestRaw, startDraft, submitDraft, type DraftResponse, type FormOptions, type IntakeBootstrap } from "../client/api";
import { ServerDraftStore } from "../client/serverDraftStore";
import { RevisionMemoryStore } from "../client/revisionMemoryStore";
import { createRevisionSnapshot, getRevisionDetail, isPartialOutcome, postRevision, revisionOutcome, type RevisionDetail, type RevisionReasonCode, type RevisionSnapshot } from "../client/revisions";
import { formTagExtensions, PinnedDefinitionError, readDefinitionPin, resolveNewInterviewDefinition, resolveSavedEnvelopeDefinition, withDefinitionPin, type DefinitionCache, type DefinitionPin, type ResolvedInstrument } from "../formDefinitionRuntime";
import { FormDefinitionError, type DefinitionRequest } from "../formDefinitions";
import { FormDefinitionHistoryError } from "../formDefinitionHistory";
import type { Prefill } from "../cases";
import { readWebRecall, recallFromData, withInterviewerRecall, writeWebRecall } from "../interviewerRecall";
import { refusalFieldsText, refusalProblems } from "../refusalText";
import { fetchProjectConsentConfig, getDraftConsent, postDraftConsent, type ConsentRecordEnvelope, type DraftConsentStatus, type ProjectConsentConfig } from "../consent";
import { useAppState } from "../AppState";
import { questionnaireDefault, questionnaireLocales, t, type StringKey } from "../i18n";
import { radius, useTheme } from "../theme";
import { useWhoFormTheme } from "../whoWebTheme";
import { applyTranslations } from "../translations";
import { Button, errorReference, useUiStyles } from "../ui";
import { AppHeaderBar } from "./AppHeader";
import { browserErrorText, WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { InterviewCaseStrip } from "./InterviewCaseStrip";
import { RespondentConsentPanel } from "./StationConsentPanel";
import { guardedNavigate, useNavigationGuard } from "./navigationGuard";
import { loadWhoCoreRuntime, loadWhoWebRuntime, type WhoWebRuntime } from "./whoRuntimeLoader";
import type { WhoCoreRuntime } from "../whoCoreRuntime";
import { RefusalPanel } from "../RefusalPanel";
import { ConfirmDialog } from "../ConfirmDialog";
import { isRefused, refusalAnswers } from "../refusalBoundary";

/**
 * The package's own UI strings (en, plus its built-in Hindi and French packs)
 * with the "More sections appear as you answer" note blanked: the owner
 * dropped it from the section progress. Supplying uiTranslations replaces the
 * built-in packs, so they are spread back in; every other locale falls back
 * to the blank English entry.
 */
export function interviewUiTranslations(core: WhoCoreRuntime) {
  return Object.fromEntries(
    Object.entries({ en: {}, ...core.WHO_VA_BUILT_IN_UI_TRANSLATIONS }).map(([code, strings]) => [code, { ...strings, moreSectionsNote: "" }])
  );
}

interface WhoInterviewRuntime {
  core: WhoCoreRuntime;
  web: WhoWebRuntime;
}

function initialDataFromLoadedRuntime(core: WhoCoreRuntime, prefill: Prefill | undefined): SubmissionData | undefined {
  if (!prefill) return undefined;
  let data: SubmissionData = {};
  try {
    data = core.createWhoVaInitialDataFromPrefill({ interviewer: prefill.interviewer, deceased: prefill.deceased }) ?? {};
  } catch {
    console.warn("prefill mapping failed");
  }
  return { ...data, ...(prefill.answers ?? {}) };
}

/**
 * The package's footer row (Back, Save draft, Preview, Next; testID
 * "form-footer") runs edge to edge and sticks to the bottom of a phone
 * viewport. The scroller is WebShell's, which already ends above BottomTabs
 * (its in-flow spacer), so bottom 0 sits directly on the tab bar and follows
 * it when the keyboard hides the bar. The package's own ScrollView never
 * scrolls here (it grows with its content) but would capture the sticky row,
 * so it is made overflow-visible. From 768px the row sits in flow at the end
 * of the form card.
 *
 * The case strip spans the phone viewport the same way, so the form never
 * shows beside it while it is pinned at the top.
 */
export const INTERVIEW_FORM_CSS = `
  #digitva-who-form-theme [stroke="#004687"] {
    stroke: var(--who-2022-web-color-brand-deep) !important;
  }
  #digitva-who-form-theme [stroke="#ffffff"],
  #digitva-who-form-theme [stroke="#fff"] {
    stroke: var(--who-2022-web-color-on-accent, #ffffff) !important;
  }
  @media (max-width: 767px) {
    #digitva-who-form-theme div:has(> div > [data-testid="form-footer"]) {
      overflow: visible;
    }
    #digitva-interview-case-strip {
      width: 100vw;
      margin-inline: calc(50% - 50vw);
      padding-inline: 8px;
      box-sizing: border-box;
    }
    #digitva-who-form-theme [data-testid="form-footer"] {
      position: sticky;
      bottom: 0;
      z-index: 2;
      width: 100vw;
      margin-inline: calc(50% - 50vw);
      margin-bottom: 0;
      padding: 8px;
      background: var(--who-2022-web-color-surface);
      border-top: 1px solid var(--who-2022-web-color-border);
    }
  }
`;

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

/** Name a form-definition failure instead of reporting it as a server error. */
export function definitionErrorText(error: unknown): string | undefined {
  if (error instanceof FormDefinitionError && error.code === "incompatible_engine") return t("formDefinitionUpdateApp");
  if (error instanceof PinnedDefinitionError) {
    return t(error.code === "current_definition_unavailable" ? "formDefinitionCurrentUnavailable" : "formDefinitionSavedUnavailable");
  }
  if (error instanceof FormDefinitionHistoryError) return t("formDefinitionSavedUnavailable");
  if (error instanceof FormDefinitionError) return t("formDefinitionUnverified");
  return undefined;
}

export { refusalFieldsText };

const SUMMARY_ANSWER_KEYS = [
  "Id10017",
  "Id10018",
  "Id10019",
  "Id10021",
  "Id10023",
  "ageInYears",
  "ageInYears2",
  "age_adult",
  "age_child_years",
  "dob_known",
  "dob_type",
  "dob_month_year",
  "dob_year",
] as const;

/** Keep the server's actionable stale-draft explanation visible to the interviewer. */
export function interviewErrorText(error: unknown, instrument?: InstrumentDefinition, language = "en"): string {
  const definitionText = definitionErrorText(error);
  if (definitionText) return definitionText;
  if (error instanceof ClientApiError && error.code === "draft_stale") {
    const message = error.payload?.error;
    if (typeof message === "string" && message.trim()) return message.trim().slice(0, 500);
  }
  // A refused submit names what to fix (consent, Id10013, identity): show the server's fixed rule
  // text, the section and question it points at, and the Ref.
  if (error instanceof ClientApiError && error.status === 422) {
    const message = error.payload?.error;
    if (typeof message === "string" && message.trim()) {
      const fix = refusalFieldsText(error.payload?.fields, instrument, language);
      return [message.trim().slice(0, 500), fix && `${t("fixFields")} ${fix}`, errorReference(error)].filter(Boolean).join("\n");
    }
  }
  return browserErrorText(error);
}

function revisionErrorText(error: unknown): string {
  const definitionText = definitionErrorText(error);
  if (definitionText) return definitionText;
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
  instrument: InstrumentDefinition,
  formVersion = "2022"
): RevisionDetail["envelope"] {
  const acceptedInstrumentIds = new Set([instrument.id, "WHO_2022_VA", "va_who_2022"]);
  if (
    (envelope.formVersion && envelope.formVersion !== formVersion) ||
    (envelope.instrumentId && !acceptedInstrumentIds.has(envelope.instrumentId)) ||
    (envelope.instrumentVersion && envelope.instrumentVersion !== instrument.version)
  ) {
    throw new Error("revision_instrument_mismatch");
  }
  return {
    ...envelope,
    formVersion: envelope.formVersion || formVersion,
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
  const { bootstrap, chooseUiLocale, onBeforeLock } = appState;
  // Training routes are wrapped in TrainingScope; the scoped bootstrap is authoritative.
  const requestCsrf = bootstrap?.csrf;
  const { definitionCache, hasServedDefinition, markServedDefinition, sessionGeneration } =
    appState as typeof appState & BrowserDefinitionAccess;
  const styles = useUiStyles();
  const theme = useTheme();
  const whoTheme = useWhoFormTheme();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [draftId, setDraftId] = useState(params.draftId);
  const [draft, setDraft] = useState<DraftResponse>();
  const [revision, setRevision] = useState<RevisionDetail>();
  // A training interview returns to the Training menu's Interview list, not to the real Interview list.
  const collectionPath = isTrainingProject(bootstrap?.access, draft?.draft.project_id ?? params.revisionProjectId ?? params.projectId)
    ? TRAINING_INTERVIEW_HOME : "/collection";
  const [instrument, setInstrument] = useState<InstrumentDefinition>();
  const [resolvedInstrument, setResolvedInstrument] = useState<ResolvedInstrument>();
  const [locale, setLocale] = useState("en");
  const [locales, setLocales] = useState<FormOptions["available_locales"]>([]);
  const [store, setStore] = useState<ServerDraftStore | RevisionMemoryStore>();
  const [controller, setController] = useState<WhoVaDraftController>();
  const [whoRuntime, setWhoRuntime] = useState<WhoInterviewRuntime>();
  const whoRuntimeRef = useRef<WhoInterviewRuntime | undefined>(undefined);
  const [runtimeError, setRuntimeError] = useState<unknown>();
  const [runtimeRetry, setRuntimeRetry] = useState(0);
  const [runtimeLoading, setRuntimeLoading] = useState(false);
  // What a refused submit named, listed in the form's problems popup instead of a red banner.
  const [serverProblems, setServerProblems] = useState<ReturnType<typeof refusalProblems>>();
  // Changed since the last acknowledged save. A ref, not state: the navigation guard reads it in the same tick a
  // save or submit settles, and nothing renders from it.
  const dirtyRef = useRef(false);
  // The answers of the latest change: a save of older answers settling later must not mark newer ones saved.
  const changedDataRef = useRef<SubmissionData | undefined>(undefined);
  // The last autosave or leave-save failed; the leave dialog then says the answers could not be saved.
  const saveFailedRef = useRef(false);
  const [busy, setBusy] = useState(false);
  // The cookie session died mid-interview: autosave is paused until the user signs in again (digitva-fvbc).
  const [signedOut, setSignedOut] = useState(false);
  const [translationFallback, setTranslationFallback] = useState(false);
  // The draft's own form could not be recovered and it now uses the current one.
  const [formAdopted, setFormAdopted] = useState(false);
  const [message, setMessage] = useState("");
  const [revisionReason, setRevisionReason] = useState<RevisionReasonCode>();
  const [needsNewSnapshot, setNeedsNewSnapshot] = useState(false);
  const [caseStripHeight, setCaseStripHeight] = useState(0);
  const [formOptions, setFormOptions] = useState<FormOptions>();
  const [liveAnswers, setLiveAnswers] = useState<Record<string, unknown>>({});
  const [whoRefused, setWhoRefused] = useState(false);
  const [refusalAge, setRefusalAge] = useState("");
  const [refusalSex, setRefusalSex] = useState("");
  const [changingConsent, setChangingConsent] = useState(false);
  const [confirmWhoGrant, setConfirmWhoGrant] = useState(false);
  const [saveInfo, setSaveInfo] = useState<{ savedSections: number; updatedAt?: string }>({ savedSections: 0 });
  const [welcomePending, setWelcomePending] = useState(false);
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
  // The open interview, read by the reset below (which must not re-run when it changes) so answers
  // typed since the last save reach the server before the store is dropped.
  const openInterviewRef = useRef({ store, controller, userId: loadedBootstrap?.user.user_id });
  openInterviewRef.current = { store, controller, userId: loadedBootstrap?.user.user_id };
  const resetSaveRef = useRef<Promise<void>>(Promise.resolve());
  const draftPrefill = draft?.prefill as Prefill | undefined;
  // Respondent consent (digitva-athy): a draft interview opens its form only once the case has a
  // decision on file where the project requires one. Revisions are never gated here.
  const [consentGate, setConsentGate] = useState<{ status: DraftConsentStatus; config: ProjectConsentConfig | null }>();
  const [consentCheck, setConsentCheck] = useState(0);
  const consentRefused = consentGate?.status.decision === "refused";
  const coveredFields = useMemo(
    () => new Set(consentRefused ? consentGate?.status.covered_fields ?? [] : []),
    [consentGate, consentRefused],
  );
  // A refusal locks the covered questions (the respondent's name, family and address answers) empty.
  const lockedQuestionNames = useMemo(
    () => coveredFields.size ? [...(draftPrefill?.lockedQuestionNames ?? []), ...coveredFields] : draftPrefill?.lockedQuestionNames,
    [coveredFields, draftPrefill],
  );

  const initialise = useCallback(async (isInitializationActive: () => boolean) => {
    if (!bootstrap || !definitionCache || !requestCsrf) return;
    const currentDefinitionCache: DefinitionCache = definitionCache;
    const generation = generationRef.current;
    const requestSessionGeneration = sessionGeneration;
    const isCurrent = () => isInitializationActive() && generationRef.current === generation &&
      bootstrapRef.current === bootstrap && requestSessionGeneration === sessionGeneration;
    if (!isCurrent()) return;
    let runtime = whoRuntimeRef.current;
    if (!runtime) {
      setRuntimeLoading(true);
      setRuntimeError(undefined);
      try {
        const [core, web] = await Promise.all([loadWhoCoreRuntime(), loadWhoWebRuntime()]);
        runtime = { core, web };
        whoRuntimeRef.current = runtime;
        if (isCurrent()) setWhoRuntime(runtime);
      } catch (error) {
        if (isCurrent()) setRuntimeError(error);
        throw error;
      } finally {
        if (isCurrent()) setRuntimeLoading(false);
      }
    }
    if (!runtime || !isCurrent()) return;
    const loadedRuntime = runtime;
    setLoadedBootstrap(undefined);
    // Load only after the reset's save of the previous store, or the draft read misses those answers.
    await resetSaveRef.current;
    if (!isCurrent()) return;
    // "all": a training interview opens here too (the lists, not this by-id screen, keep the two apart).
    const nextIntake = await getIntakeContext(requestCsrf, "interview", "all");
    if (!isCurrent()) return;
    setIntake(nextIntake);
    let nextDraftId = params.draftId;
    let nextRevision: RevisionDetail | undefined;
    let options: FormOptions | undefined;
    let resolved: ResolvedInstrument | undefined;
    let adopted = false;
    const request = definitionRequest(requestCsrf, isCurrent);
    const accountId = bootstrap.user.user_id;

    async function resolveNew(projectId: string, formOptions: FormOptions): Promise<ResolvedInstrument> {
      instrumentCode(formOptions);
      const bundled = loadedRuntime.core.createWhoVa2022Instrument(formOptions.enabled_extensions ?? []);
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
      nextRevision = await getRevisionDetail(bootstrap.links.intakeDrafts, params.revisionDraftId, requestCsrf, {
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
      const { case: caseRow } = await getCaseDetail(bootstrap.links.intakeCases, params.deathId, requestCsrf);
      if (!isCurrent()) return;
      if (!caseRow?.prefill) throw new Error("caseActionsUnavailable");
      if (!caseRow.project_id || !caseRow.site_id) throw new Error("case_context_missing");
      if (caseRow.my_draft_id) {
        nextDraftId = caseRow.my_draft_id;
        setDraftId(nextDraftId);
      } else {
        options = await getProjectFormOptions(caseRow.project_id, requestCsrf);
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
          requestCsrf
        );
        if (!isCurrent()) return;
        nextDraftId = started.draft.draft_id;
        setDraftId(nextDraftId);
      }
    }
    if (!nextDraftId && !params.deathId && params.projectId && params.siteId) {
      const context = nextIntake.context.find((entry) => entry.project_id === params.projectId && entry.site_id === params.siteId);
      if (!context || !["direct", "both"].includes(context.web_intake_mode ?? "")) throw new Error("intake_configuration_unavailable");
      options = await getProjectFormOptions(params.projectId, requestCsrf);
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
        requestCsrf
      );
      if (!isCurrent()) return;
      nextDraftId = started.draft.draft_id;
      setDraftId(nextDraftId);
    }
    if (!nextDraftId) throw new Error("draft_missing");
    const nextDraft = nextRevision ?? await getDraft(bootstrap.links.intakeDrafts, nextDraftId, requestCsrf);
    if (!isCurrent()) return;
    options ??= await getProjectFormOptions(nextDraft.draft.project_id, requestCsrf);
    if (!isCurrent()) return;
    instrumentCode(options);
    if (!resolved) {
      if (!nextRevision && !readDefinitionPin(nextDraft.envelope) && !nextDraft.envelope.instrumentVersion) {
        resolved = await resolveNew(nextDraft.draft.project_id, options);
      } else {
        const bundledFallback = loadedRuntime.core.createWhoVa2022Instrument(options.enabled_extensions ?? []);
        const projectId = nextDraft.draft.project_id;
        const formOptions = options;
        resolved = await resolveSavedEnvelopeDefinition({
          accountId: bootstrap.user.user_id,
          projectId: nextDraft.draft.project_id,
          envelope: nextDraft.envelope,
          request,
          cache: currentDefinitionCache,
          narrationLanguageCodes: narrationLanguageCodes(options),
          bundledLegacyDefinitions: [],
          bundledOriginal: {
            instrument: bundledFallback,
            instrumentVersion: bundledFallback.version,
            extensions: options.enabled_extensions ?? [],
          },
          // A revision must keep its submitted form, so only a draft moves on.
          adoptCurrentDefinition: nextRevision ? undefined : async () => {
            adopted = true;
            return resolveNew(projectId, formOptions);
          },
        });
      }
    }
    if (!isCurrent()) return;
    const base = resolved.instrument;
    const normalizedRevision = nextRevision
      ? {
          ...nextRevision,
          envelope: withDefinitionPin(normalizeRevisionEnvelope(nextRevision.envelope, base, loadedRuntime.core.WHO_VA_FORM_VERSION), resolved.pin),
        }
      : undefined;
    const savedLocale = nextDraft.envelope.locale;
    const nextLocale = savedLocale ?? questionnaireDefault(options.available_locales, options.default_locale);
    const translated = await translatedResolvedInstrument(resolved, nextLocale, options, requestCsrf);
    if (!isCurrent()) return;
    const nextInstrument = translated.instrument;
    setTranslationFallback(translated.fallback);
    await chooseUiLocale(nextLocale);
    if (!isCurrent()) return;
    const sectionOf = new Map(base.questions.map((question) => [question.name, question.sectionPath.at(-1) ?? "_root"]));
    const prefill = nextDraft.prefill as Prefill;
    // A new interview only (never a revision): the interviewer's own details from their last one.
    const prefillData = nextRevision
      ? (initialDataFromLoadedRuntime(loadedRuntime.core, prefill) as SubmissionData)
      : withInterviewerRecall(
          initialDataFromLoadedRuntime(loadedRuntime.core, prefill),
          readWebRecall(bootstrap.user.user_id),
          bootstrap.user.name,
        );
    const initialData = normalizedRevision
      ? { ...prefillData, ...normalizedRevision.envelope.data }
      : prefillData;
    const hasStartedSection = Boolean(
      nextDraft.draft.current_section || nextDraft.envelope?.currentSection
    );
    const shouldShowWelcome =
      !nextRevision &&
      !hasStartedSection &&
      (options.enabled_extensions ?? []).includes("intake_screen") &&
      Boolean(options.intake_note?.trim());
    const initialSavedCount =
      typeof nextDraft.draft.sections_saved === "number"
        ? nextDraft.draft.sections_saved
        : Object.keys((nextDraft.envelope?.data as Record<string, unknown>) ?? {}).length > 0
          ? 1
          : 0;
    const nextStore = normalizedRevision
      ? new RevisionMemoryStore({ ...normalizedRevision.envelope, data: initialData })
      : new ServerDraftStore({
          endpoint: bootstrap.links.intakeDrafts,
          csrf: requestCsrf,
          sectionOf,
          initialData,
          initialDataVersion: nextDraft.draft.updated_at,
          definitionPin: resolved.pin,
          identity: {
            instrumentId: nextInstrument.id,
            instrumentVersion: resolved.pin?.instrumentVersion ?? nextInstrument.version,
            firstSection: nextInstrument.sections[0]?.name ?? ""
          },
          locale: nextLocale,
          translationVersion: nextDraft.envelope.translation_version ?? options.translation_versions?.[nextLocale] ?? 0,
          onSaveAcknowledged: (info) => {
            if (!isCurrent()) return;
            setSaveInfo(info);
          },
          onError: (error) => {
            if (!isCurrent()) return;
            saveFailedRef.current = true;
            setMessage(interviewErrorText(error));
          },
          onSignedOut: () => {
            if (!isCurrent()) return;
            saveFailedRef.current = true;
            setSignedOut(true);
          }
        });
    if (nextStore instanceof ServerDraftStore) await nextStore.load(nextDraftId);
    if (!isCurrent()) return;
    setFormOptions(options);
    setWelcomePending(shouldShowWelcome);
    setLiveAnswers({
      ...(initialData as Record<string, unknown>),
      ...((nextDraft.envelope?.data as Record<string, unknown>) ?? {}),
    });
    setSaveInfo({
      savedSections: initialSavedCount,
      updatedAt: hasStartedSection ? nextDraft.draft.updated_at : undefined,
    });
    setDraft(nextDraft);
    setRevision(normalizedRevision);
    setLocale(nextLocale);
    setLocales(questionnaireLocales(options.available_locales));
    setResolvedInstrument(resolved);
    setFormAdopted(adopted);
    setInstrument(nextInstrument);
    setStore(nextStore);
    setLoadedBootstrap(bootstrap);
  }, [bootstrap, chooseUiLocale, definitionCache, hasServedDefinition, markServedDefinition, params.deathId, params.draftId, params.orgUnitId, params.projectId, params.revisionDraftId, params.revisionProjectId, params.revisionSiteId, params.revisionVaSid, params.siteId, runtimeRetry, sessionGeneration]);

  useEffect(() => {
    const open = openInterviewRef.current;
    // Same account only: another user's session must not write this draft.
    if (open.store instanceof ServerDraftStore && open.userId && open.userId === bootstrapRef.current?.user.user_id) {
      const previousStore = open.store;
      resetSaveRef.current = (open.controller?.saveDraft() ?? Promise.resolve())
        .then(() => previousStore.flush())
        .catch(() => undefined);
    }
    setIntake(undefined);
    setDraftId(params.draftId);
    setDraft(undefined);
    setRevision(undefined);
    setInstrument(undefined);
    setResolvedInstrument(undefined);
    setFormAdopted(false);
    setFormOptions(undefined);
    setLiveAnswers({});
    setSaveInfo({ savedSections: 0 });
    setWelcomePending(false);
    setStore(undefined);
    setController(undefined);
    dirtyRef.current = false;
    changedDataRef.current = undefined;
    saveFailedRef.current = false;
    setRevisionReason(undefined);
    setNeedsNewSnapshot(false);
    setConsentGate(undefined);
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

  // The consent decision on file for this draft's case; the notice only when one is still needed.
  useEffect(() => {
    if (!bootstrap || !draftId || !draft || revision) return undefined;
    let live = true;
    void (async () => {
      const status = await getDraftConsent(bootstrap.links.intakeDrafts, draftId, requestCsrf!);
      const config = status.consent_required && !status.decision
        ? await fetchProjectConsentConfig(draft.draft.project_id, requestCsrf!)
        : null;
      if (live) {
        if (status.decision === "refused" && store instanceof ServerDraftStore) store.enterRefusal();
        setConsentGate({ status, config });
        const saved = draft.envelope.data;
        setWhoRefused(saved?.Id10013 === "no");
        if (saved?.Id10013 === "no" && store instanceof ServerDraftStore) store.enterRefusal();
        setRefusalAge(typeof saved?.refusal_age_group === "string" ? saved.refusal_age_group : "");
        setRefusalSex(typeof saved?.refusal_sex === "string" ? saved.refusal_sex : "");
      }
    })().catch((error) => { if (live) setMessage(interviewErrorText(error)); });
    return () => { live = false; };
  }, [bootstrap, draftId, draft, revision, consentCheck]);

  async function recordConsent(envelope: ConsentRecordEnvelope) {
    if (!bootstrap || !draftId || !consentGate) return;
    setBusy(true);
    setMessage("");
    try {
      const status = await postDraftConsent(bootstrap.links.intakeDrafts, draftId, envelope, requestCsrf!);
      if (status.decision === "refused" && store instanceof ServerDraftStore) store.enterRefusal();
      if (status.decision === "granted" && consentRefused && store instanceof ServerDraftStore) {
        await store.resumeAfterConsentGrant();
      }
      setConsentGate({ ...consentGate, status });
      setChangingConsent(false);
      if (status.decision === "granted" && typeof window !== "undefined") window.location.reload();
    } catch (error) {
      setMessage(interviewErrorText(error));
    } finally {
      setBusy(false);
    }
  }

  // A best-effort save as the page unloads; the navigation guard owns the browser's leave prompt.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleBeforeUnload = () => {
      void controller?.saveDraft().then(() => store instanceof ServerDraftStore ? store.flush() : undefined).catch(() => undefined);
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [controller, store]);

  // Sign-out (manual or idle) waits for the pending autosave instead of aborting it.
  useEffect(() => onBeforeLock(async () => {
    await controller?.saveDraft();
    if (store instanceof ServerDraftStore) await store.flush();
  }), [controller, store, onBeforeLock]);

  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return undefined;
    const style = document.createElement("style");
    style.textContent = INTERVIEW_FORM_CSS;
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
      const options = await getProjectFormOptions(draft.draft.project_id, requestCsrf!);
      if (!isCurrent()) return false;
      const next = await translatedResolvedInstrument(resolvedInstrument, nextLocale, options, requestCsrf!);
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
      const acknowledgement = await postRevision(requestCsrf!, snapshot);
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
        dirtyRef.current = false;
        router.replace({ pathname: collectionPath as never, params: { submitted: "correction" } });
      } else {
        dirtyRef.current = true;
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
    setServerProblems(undefined);
    try {
      try {
        await controller?.saveDraft();
        if (!isCurrent()) return;
        if (store instanceof ServerDraftStore) await store.flush();
      } catch (error) {
        if (!isCurrent()) return;
        if (!(store instanceof ServerDraftStore) || !(error instanceof ClientApiError) || error.status !== 409) throw error;
        const currentDraft = await getDraft(bootstrap.links.intakeDrafts, draftId, requestCsrf!);
        if (!isCurrent()) return;
        if (currentDraft.draft.status !== "submitted") throw error;
      }
      if (!isCurrent()) return;
      if (store instanceof ServerDraftStore && typeof store.recordTimelineEvent === "function") {
        await store.recordTimelineEvent("submit_started");
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
      // Under a refusal the covered answers never leave the page (the server refuses them).
      const data = coveredFields.size && result.data
        ? Object.fromEntries(Object.entries(result.data).filter(([name]) => !coveredFields.has(name))) as typeof result.data
        : result.data;
      const submission = await submitDraft(
        bootstrap.links.intakeDrafts,
        draftId,
        { valid: result.valid, issues: result.issues, data },
        requestCsrf!,
        store instanceof ServerDraftStore ? store.getServerUpdatedAt() : undefined,
      );
      if (!isCurrent()) return;
      dirtyRef.current = false;
      const sent = { submitted: "1", ...(submission.draft.unique_id ? { submittedId: submission.draft.unique_id } : {}) };
      if (submission.superseded) {
        router.replace({ pathname: collectionPath as never, params: { ...sent, superseded: "1" } });
      } else if (submission.kept === "server") {
        router.replace({ pathname: collectionPath as never, params: {
          ...sent,
          submissionHistory: "1",
          submissionLocked: submission.locked === true ? "1" : "0",
          ...(submission.can_code_now === true ? { canCodeNow: "1" } : {}),
          ...(submission.can_code_now === true && submission.draft.unique_id ? { readyUniqueId: submission.draft.unique_id } : {}),
          ...(submission.can_code_now === true ? { readyVaSid: submission.va_sid } : {}),
        } });
      } else if (submission.can_code_now === true) {
        router.replace({ pathname: collectionPath as never, params: {
          ...sent,
          canCodeNow: "1",
          ...(submission.draft.unique_id ? { readyUniqueId: submission.draft.unique_id } : {}),
          readyVaSid: submission.va_sid,
        } });
      } else {
        router.replace({ pathname: collectionPath as never, params: sent });
      }
    } catch (error) {
      // The project began requiring consent after this page checked: ask for it now.
      if (isCurrent() && error instanceof ClientApiError && error.code === "consent_required") setConsentCheck((n) => n + 1);
      // A refused submit that names what to fix goes to the problems popup; any other error stays a message.
      const refused =
        isCurrent() && error instanceof ClientApiError && error.status === 422 && !(store instanceof RevisionMemoryStore)
          ? refusalProblems(
              {
                message: [typeof error.payload?.error === "string" ? error.payload.error.trim().slice(0, 500) : "", errorReference(error)]
                  .filter(Boolean)
                  .join(" · "),
                fields: error.payload?.fields
              },
              t("refusalNotAcceptedNoReason")
            )
          : undefined;
      if (refused) {
        setServerProblems(refused);
        controller?.showProblems();
      } else if (isCurrent()) {
        setMessage(store instanceof RevisionMemoryStore ? revisionErrorText(error) : interviewErrorText(error, instrument, locale));
      }
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }

  /** The leave dialog's Save and leave: the form's save, then the server write; a held revision cannot be saved here. */
  const saveForLeave = useCallback(async () => {
    const requestBootstrap = bootstrap;
    const generation = generationRef.current;
    const isCurrent = () => bootstrapRef.current === requestBootstrap && generationRef.current === generation;
    try {
      await controller?.saveDraft();
      if (!isCurrent()) return false;
      if (store instanceof RevisionMemoryStore && dirtyRef.current) {
        setMessage(t("revisionUnsavedWarning"));
        return false;
      }
      if (store instanceof ServerDraftStore) await store.flush();
      if (!isCurrent()) return false;
      return true;
    } catch (error) {
      if (!isCurrent()) return false;
      saveFailedRef.current = true;
      setMessage(store instanceof RevisionMemoryStore ? revisionErrorText(error) : interviewErrorText(error));
      return false;
    }
  }, [bootstrap, controller, store]);

  // Answers autosave about 600 ms after the last change, so the leave dialog only opens while that save is pending
  // or after it failed.
  useNavigationGuard(() => dirtyRef.current, saveForLeave, () => saveFailedRef.current);

  const localeLabel = useMemo(() => locales?.find((entry) => entry.code === locale)?.label ?? locale, [locale, locales]);
  const availableLocales = locales ?? [];
  const showCaseStrip = Boolean(draft);
  const stripPrefill = draft?.draft.death_id || revision ? draftPrefill : undefined;
  const locationLabel = useMemo(() => {
    if (!draft) return null;
    const projectId = draft.draft.project_id;
    const siteId = draft.draft.site_id;
    const orgUnitId = draft.draft.org_unit_id;
    const contextList = Array.isArray(intake?.context) ? intake.context : [];
    const entry = contextList.find((item) => item.project_id === projectId && item.site_id === siteId);
    if (orgUnitId) {
      const unit = entry?.org_units?.find((item) => item.org_unit_id === orgUnitId);
      if (unit) {
        const projectEntry = [
          ...(bootstrap?.access.projects ?? []),
          ...(bootstrap?.access.training?.project ? [bootstrap.access.training.project] : []),
        ].find((p) => p.project_id === projectId);
        const levelName =
          unit.level_name ??
          projectEntry?.levels?.find((l) => l.level_code === unit.level_code)?.level_name;
        const label = [levelName, unit.unit_name].filter(Boolean).join(" ");
        if (label) return label;
      }
      if (draft.draft.org_unit_name) return draft.draft.org_unit_name;
    }
    if (entry) {
      return [entry.project_name || entry.project_id, entry.site_name || entry.site_id]
        .filter(Boolean)
        .join(" / ") || null;
    }
    return [projectId, draft.draft.site_name || siteId].filter(Boolean).join(" / ") || null;
  }, [bootstrap, draft, intake]);
  const saveStatusLabel = useMemo(() => {
    if (saveInfo.updatedAt && saveInfo.savedSections > 0) {
      let time = saveInfo.updatedAt;
      if (!/^\d{2}:\d{2}:\d{2}$/.test(time)) {
        const parsed = new Date(time);
        if (!Number.isNaN(parsed.getTime())) {
          time = parsed.toTimeString().slice(0, 8);
        }
      }
      return saveInfo.savedSections === 1
        ? t("interviewSavedSectionOne", { time })
        : t("interviewSavedSections", { time, count: saveInfo.savedSections });
    }
    return t("interviewNotSavedYet");
  }, [saveInfo]);
  const consentPending = !revision && (!consentGate || (consentGate.status.consent_required && !consentGate.status.decision));
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
        "--who-2022-web-sticky-top": `${showCaseStrip ? caseStripHeight : 0}px`
      } as unknown as ViewStyle)
    : undefined;
  const WhoVaFormComponent = whoRuntime?.web.WhoVaForm;
  const uiTranslations = useMemo(
    () => whoRuntime ? interviewUiTranslations(whoRuntime.core) : undefined,
    [whoRuntime],
  );
  const updateLiveAnswers = useCallback((data: Record<string, unknown> | undefined) => {
    if (!data || typeof data !== "object") return;
    setLiveAnswers((prev) => {
      for (const key of SUMMARY_ANSWER_KEYS) {
        if (prev[key] !== data[key]) {
          const next: Record<string, unknown> = {};
          for (const k of SUMMARY_ANSWER_KEYS) {
            if (data[k] !== undefined) next[k] = data[k];
          }
          return next;
        }
      }
      return prev;
    });
  }, []);
  const handleFormChange = useCallback((data: SubmissionData) => {
    if (!(store instanceof RevisionMemoryStore) && isRefused(data)) {
      if (store instanceof ServerDraftStore) store.enterRefusal();
      setWhoRefused(true);
      void controller?.saveDraft().catch(() => undefined);
    }
    if (store instanceof RevisionMemoryStore) revisionGenerationRef.current += 1;
    setNeedsNewSnapshot(false);
    dirtyRef.current = true;
    changedDataRef.current = data;
    updateLiveAnswers(data as Record<string, unknown>);
    if (!(store instanceof RevisionMemoryStore) && loadedBootstrap) {
      writeWebRecall(loadedBootstrap.user.user_id, recallFromData(data));
    }
  }, [controller, loadedBootstrap, store, updateLiveAnswers]);
  const handleDraftSaved = useCallback((saved?: { data?: SubmissionData }) => {
    if (!(store instanceof ServerDraftStore)) return;
    saveFailedRef.current = false;
    if (saved?.data === changedDataRef.current) dirtyRef.current = false;
    updateLiveAnswers(saved?.data as Record<string, unknown> | undefined);
  }, [store, updateLiveAnswers]);
  const handleDraftError = useCallback((error: unknown) => {
    saveFailedRef.current = true;
    if (store instanceof ServerDraftStore && store.isSignedOut()) return;
    setMessage(revision ? revisionErrorText(error) : browserErrorText(error));
  }, [revision, store]);

  const resumeAfterSignIn = useCallback(async () => {
    if (!(store instanceof ServerDraftStore)) return;
    setBusy(true);
    try {
      await store.resume();
      saveFailedRef.current = false;
      setSignedOut(false);
      setMessage("");
    } catch (error) {
      setMessage(store.isSignedOut() || error instanceof ClientApiError ? t("sessionEndedStillOut") : browserErrorText(error));
    } finally {
      setBusy(false);
    }
  }, [store]);

  async function saveRefusal() {
    if (!bootstrap || !draftId || !(store instanceof ServerDraftStore)) return;
    setBusy(true);
    try {
      await store.flush();
      const current = await getDraft(bootstrap.links.intakeDrafts, draftId, requestCsrf!);
      const data = refusalAnswers({ ...current.envelope.data, ...(whoRefused ? { Id10013: "no" } : {}), refusal_age_group: refusalAge, refusal_sex: refusalSex }) as SubmissionData;
      await submitDraft(bootstrap.links.intakeDrafts, draftId, { valid: true, issues: [], data }, requestCsrf!, current.draft.updated_at);
      dirtyRef.current = false;
      router.replace({ pathname: collectionPath as never, params: { submitted: "1" } });
    } catch (error) { setMessage(interviewErrorText(error)); } finally { setBusy(false); }
  }

  async function changeRefusal() {
    if (!bootstrap || !draftId || !draft || !consentGate) return;
    if (consentRefused) {
      try {
        const config = await fetchProjectConsentConfig(draft.draft.project_id, requestCsrf!);
        setConsentGate({ ...consentGate, config });
        setChangingConsent(true);
      } catch (error) { setMessage(interviewErrorText(error)); }
      return;
    }
    setConfirmWhoGrant(true);
  }

  async function grantWhoConsent() {
    if (!bootstrap || !draftId || !(store instanceof ServerDraftStore)) return;
    setBusy(true);
    try {
      await store.flush();
      const current = await getDraft(bootstrap.links.intakeDrafts, draftId, requestCsrf!);
      await requestClientJson(`${bootstrap.links.intakeDrafts}/${encodeURIComponent(draftId)}`, {
        method: "PATCH", csrf: requestCsrf!, json: { sections: { _other: { Id10013: "yes" } }, resume_refused: true, if_updated_at: current.draft.updated_at },
      });
      dirtyRef.current = false;
      if (typeof window !== "undefined") window.location.reload();
    } catch (error) { setMessage(interviewErrorText(error)); } finally { setBusy(false); setConfirmWhoGrant(false); }
  }

  return (
    <WebShell
      title={t(revision ? "revisionTitle" : "interviewTitle")}
      // The header bar, the title row with the language switch and Back to collection scroll away with the form;
      // only the case strip stays pinned at the top.
      lead={<AppHeaderBar sticky={false} />}
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
      <ContextualHelpBanner screen="interview" />
      {runtimeError ? (
        <View style={styles.row}>
          <Text style={styles.error} accessibilityRole="alert">
            {t("interviewTitle")}: {t("serverUnavailable")}
          </Text>
          <Button
            kind="secondary"
            label={t("retry")}
            onPress={() => setRuntimeRetry((value) => value + 1)}
          />
        </View>
      ) : runtimeLoading || !WhoVaFormComponent ? (
        <Text style={styles.muted}>{t("loading")}</Text>
      ) : loadedBootstrap === bootstrap && instrument && store && draftId ? (
        <>
          {/* Leaves the interview; the footer's Back only steps to the previous
              section. Answers autosave (and the footer's Save draft saves at
              once), so there is no second Save here. */}
          <View style={styles.row}>
            <Button kind="secondary" label={t("backToCollection")} onPress={() => guardedNavigate(() => router.replace(collectionPath as never))} />
          </View>
          {showCaseStrip && !consentRefused && !whoRefused ? (
            <InterviewCaseStrip
              prefill={stripPrefill}
              onHeight={setCaseStripHeight}
              uniqueId={draft?.draft.unique_id}
              locationLabel={locationLabel}
              saveStatus={revision ? null : saveStatusLabel}
              answers={liveAnswers}
              showLiveSummary
            />
          ) : null}
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
          {formAdopted ? <Text style={styles.muted} testID="form-adopted-notice">{t("formDefinitionAdopted")}</Text> : null}
          {signedOut ? (
            <View testID="session-ended-prompt" accessibilityRole="alert" style={{ gap: 8 }}>
              <Text style={styles.error}>{t("sessionEndedKept")}</Text>
              <Button
                kind="primary"
                label={t("signInAgainAction")}
                onPress={() => { if (loadedBootstrap?.links.login && typeof window !== "undefined") window.open(loadedBootstrap.links.login, "_blank"); }}
              />
              <Button kind="secondary" loading={busy} label={t("sessionEndedResume")} onPress={() => void resumeAfterSignIn()} />
            </View>
          ) : null}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          {consentPending || changingConsent ? (
            consentGate ? (
              <RespondentConsentPanel
                config={consentGate.config}
                language={locale}
                clientDraftId={consentGate.status.client_draft_id}
                busy={busy}
                onDecision={(envelope) => void recordConsent(envelope)}
              />
            ) : <Text style={styles.muted}>{t("loading")}</Text>
          ) : null}
          {(consentRefused || whoRefused) && !changingConsent ? <RefusalPanel locale={locale} age={refusalAge} sex={refusalSex} onAge={setRefusalAge} onSex={setRefusalSex} onSave={() => void saveRefusal()} onChangeConsent={() => void changeRefusal()} onNew={() => { dirtyRef.current = false; router.replace(collectionPath as never); }} /> : null}
          {confirmWhoGrant ? <ConfirmDialog title={locale.startsWith("hi") ? "सहमति की पुष्टि करें" : "Confirm consent"} message={locale.startsWith("hi") ? "क्या उत्तरदाता ने अब साक्षात्कार के लिए सहमति दी है? हटाए गए उत्तर वापस नहीं आएंगे।" : "Has the respondent now agreed to the interview? Removed answers will not be restored."} confirmLabel={locale.startsWith("hi") ? "हाँ, सहमति दी" : "Yes, consent granted"} cancelLabel={t("cancel")} onConfirm={() => void grantWhoConsent()} onCancel={() => setConfirmWhoGrant(false)} /> : null}
          {!consentPending && !changingConsent && !consentRefused && !whoRefused && welcomePending && formOptions?.intake_note?.trim() ? (
            <View
              testID="interview-welcome-card"
              style={[
                welcomeStyles.card,
                { backgroundColor: theme.colors.surface, borderColor: theme.colors.border },
              ]}
            >
              <Text
                testID="interview-welcome-title"
                style={[styles.headline, welcomeStyles.title, { color: theme.colors.text }]}
              >
                {t("beforeYouBegin")}
              </Text>
              <Text
                testID="interview-welcome-note"
                style={[welcomeStyles.note, { color: theme.colors.text }]}
              >
                {formOptions.intake_note.trim()}
              </Text>
              <View style={welcomeStyles.actions}>
                <Pressable
                  testID="interview-welcome-start"
                  accessibilityRole="button"
                  accessibilityLabel={t("startQuestionnaire")}
                  onPress={() => setWelcomePending(false)}
                  style={({ pressed }) => [
                    welcomeStyles.button,
                    { backgroundColor: theme.colors.accent, opacity: pressed ? 0.85 : 1 },
                  ]}
                >
                  <Text style={[welcomeStyles.buttonText, { color: theme.colors.onAccent }]}>
                    {t("startQuestionnaire")}
                  </Text>
                </Pressable>
              </View>
            </View>
          ) : null}
          {consentPending || changingConsent || consentRefused || whoRefused || welcomePending ? null : <View nativeID="digitva-who-form-theme" style={[{ minWidth: 0, width: "100%" }, webFormStyle]}>
            <WhoVaFormComponent
              theme={whoTheme}
              key={`${draftId}:${locale}`}
              instrument={instrument}
              locale={locale}
              showEnglish={locale !== "en"}
              uiTranslations={uiTranslations}
              draftId={draftId}
              draftStore={store}
              autoSaveDraftOnChange
              autoSaveDraftIntervalMs={signedOut ? false : undefined}
              onDraftController={setController}
              onChange={handleFormChange}
              onDraftSaved={handleDraftSaved}
              onDraftError={handleDraftError}
              onComplete={complete}
              {...(serverProblems ? { serverProblems } : {})}
              lockedQuestionNames={lockedQuestionNames}
              portalThemeStyle={webFormStyle}
            />
          </View>}
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
  // Compare like with like: the pin records only tagged extensions.
  const extensions = formTagExtensions(options.enabled_extensions ?? []);
  const pinned = [...pin?.definitionExtensions ?? []].sort();
  if (
    !pin ||
    pin.instrumentVersion !== options.instrument_version ||
    pin.definitionSha256 !== options.definition_sha256 ||
    pinned.length !== extensions.length ||
    pinned.some((extension, index) => extension !== extensions[index])
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
  trigger: { minWidth: 48, minHeight: 48, borderWidth: 1, borderRadius: radius.md, alignItems: "center", justifyContent: "center" },
  triggerText: { fontSize: 16, fontWeight: "700" },
  popover: { position: "absolute", right: 0, top: 56, minWidth: 192, padding: 8, borderWidth: 1, borderRadius: radius.lg, gap: 4, zIndex: 21, shadowColor: "#000", shadowOpacity: 0.16, shadowRadius: 8, shadowOffset: { width: 0, height: 3 }, elevation: 4 },
  option: { minHeight: 48, borderRadius: 8, paddingHorizontal: 12, flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 16 },
  optionLabel: { fontSize: 16, lineHeight: 22, flexShrink: 1 },
  check: { width: 20, fontSize: 18, fontWeight: "700", textAlign: "center" }
});

const welcomeStyles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderRadius: radius.lg,
    padding: 20,
    gap: 12,
    maxWidth: 768,
    width: "100%",
    alignSelf: "center",
  },
  title: { fontSize: 20, fontWeight: "700" },
  note: { fontSize: 16, lineHeight: 22 },
  actions: { flexDirection: "row", marginTop: 4 },
  button: {
    minHeight: 44,
    paddingHorizontal: 18,
    paddingVertical: 10,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonText: { fontSize: 16, fontWeight: "600" },
});
