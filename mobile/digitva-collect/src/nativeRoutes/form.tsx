/**
 * The questionnaire for one draft, saved into the interviewer's own database.
 * Completing it marks the draft ready to send with the form engine's verdict
 * (`completion`); the upload happens from the worklist (push and purge). A
 * questionnaire the form reports invalid can be finished only when the
 * interviewer recorded the outcome as partially completed or respondent
 * unavailable, which the server accepts (web-intake.md, interview outcome).
 *
 * An interview on a case (`deathId`, a downloaded case) or on a death
 * registered on this phone (`clientDeathId`) is bound to it on its first
 * save and opens with that case's prefill and locked questions, as the web
 * form does; later opens take both from the draft itself, so a case pruned
 * from the list meanwhile changes nothing.
 */
import { deleteCoveredAttachments } from "../attachmentStore";
import {
  createWhoVa2022Instrument,
  WHO_VA_FORM_VERSION,
  type InstrumentDefinition,
  type SubmissionData,
  type SubmissionValidationResult,
} from "@drguptavivek/who-2022-va";
import {
  WhoVaForm,
  type WhoVaDraftController,
  type WhoVaSession,
} from "@drguptavivek/who-2022-va/native";
import { randomUUID } from "expo-crypto";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, AppState, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAppState } from "../AppState";
import { getOfflineProfile } from "../offlineProfile";
import { standaloneConsentConfigWithSavedNotice } from "../standalone/noticeSettings";
import { STANDALONE_DEFAULT_EXTENSIONS } from "../standalone/config";
import { STANDALONE_SITE_ID, standaloneDefinition, standaloneProject, standaloneProjectId } from "../standalone/project";
import { standaloneTranslationsForDraft, standaloneTranslationVersion } from "../standalone/translations";
import { saveStandaloneConsent } from "../standaloneConsentStore";
import { useStableAccount } from "../useStableAccount";
import {
  getCase,
  getRegistration,
  prefillFromRegistration,
  resolveDraftHost,
  type DraftHost,
  type Prefill,
  joinResidence,
} from "../cases";
import {
  createDraftStore,
  clearRefusedDraft,
  deleteUnsentDraft,
  getDraftRow,
  getMeta,
  isNeverSentDraft,
  markCompleted,
  setMeta,
  stripDraftCovered,
  type Db,
} from "../drafts";
import { authedRawRequest, SessionRevokedError, SignInRequiredError } from "../auth";
import { canStartDeathInterview } from "../deathWorkflow";
import { questionnaireDefault, questionnaireLocales, t, UI_LOCALES } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { createNativeDefinitionCache } from "../formDefinitionCache";
import {
  PinnedDefinitionError,
  resolveNewInterviewDefinition,
  resolveSavedEnvelopeDefinition,
  type ResolvedInstrument,
} from "../formDefinitionRuntime";
import { FormDefinitionError } from "../formDefinitions";
import { platformServices } from "../platform";
import { useAttachmentServices } from "../attachmentServices";
import { initialDataFromPrefill } from "../prefill";
import { RECALL_META_KEY, recallChanged, recallFromData, withInterviewerRecall, type InterviewerRecall } from "../interviewerRecall";
import {
  getCachedReferenceData,
  canUseBundledFallbackForProject,
  draftSyncDefaults,
  fetchCaseDetail,
  isUploadable,
  startsDirectly,
  targetsFrom,
  translationsForDraft,
  markProjectDefinitionServed,
  type ProjectSettings,
  type ReferenceData,
} from "../sync";
import { recoverRefusalDraft, recordDraftMilestones, recordDraftTimeline, reconcileCaseDraft } from "../draftSync";
import { applyTranslations } from "../translations";
import { ConfirmDialog } from "../ConfirmDialog";
import { useLeaveGuard } from "../leaveGuard";
import { FormTopBar, Sheet, type SaveState, type SheetItem } from "../FormTopBar";
import { revisionName } from "../revisionLabel";
import { useShell } from "../nativeShell/shellContext";
import { useToast } from "../toast";
import { RespondentConsentPanel } from "../web/StationConsentPanel";
import {
  consentForDraft,
  inheritedConsentRefused,
  DEFAULT_COVERED_FIELDS,
  getConsentConfig,
  interviewConsentGate,
  saveDraftConsent,
  storedConsent,
  withoutCovered,
} from "../consentStore";
import type { ConsentRecordEnvelope, ProjectConsentConfig } from "../consent";
import { describeError, recordError } from "../errorLog";
import { refusalProblems } from "../refusalText";
import { preSendIssues } from "../submissionChecks";
import { clearSendError, sendRefusal, type SendRefusal } from "../unsentWork";
import { coalesceLatest } from "../coalesceSaves";
import { Button, errorText, Screen, useUiStyles } from "../ui";
import { useWhoFormTheme } from "../whoWebTheme";
import { isSmartVaOptionsSnapshot, projectSmartVaSnapshot, standaloneSmartVaSnapshot, type SmartVaOptionsSnapshot, type SmartVaTarget } from "../smartva/options";
import { RefusalPanel } from "../RefusalPanel";
import { isRefused, refusalAnswers } from "../refusalBoundary";
import { runInTransaction } from "../dbTransaction";
import { ensureLocalSmartVa } from "../smartva/ensureLocal";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Loaded extends DraftHost {
  db: Db;
  project: ProjectSettings;
  config: DraftConfig;
  definition: ResolvedInstrument;
  accessVersion: number;
  hasStartedSection: boolean;
  /** The interviewer's own details from their last interview (src/interviewerRecall.ts). */
  recall?: InterviewerRecall;
  accountName?: string;
  /** Path C: no server project; the bundled form, the bundled consent notice, local translations only. */
  standalone?: boolean;
}

interface DraftConfig {
  projectId: string;
  locale: string;
  enabledExtensions: string[];
  instrumentCode: string;
  translationVersion?: number;
  intakeNote?: string | null;
  /** Exact SmartVA form/site options captured at draft creation; null freezes a missing target. */
  smartva?: SmartVaOptionsSnapshot | null;
}

type ConsentDecision = "granted" | "refused" | "none";
type ConsentView =
  | { kind: "checking" }
  /** Standalone with no bundled notice in the questionnaire language: the interview cannot be recorded. */
  | { kind: "blocked" }
  | { kind: "ask"; config: ProjectConsentConfig }
  /**
   * `required`: the project asks for consent (the top bar shows the status chip). `config`: a usable notice is
   * cached, so the decision can be changed. `decision`: what applies now (its own, else its registration's).
   */
  | { kind: "ready"; covered: string[]; unavailable?: boolean; decision: ConsentDecision; required: boolean; config?: ProjectConsentConfig };

const draftConfigKey = (draftId: string) => `draft-config:${draftId}`;

function configFromReference(project: ProjectSettings): DraftConfig {
  const options = project.form_options;
  const locale = questionnaireDefault(
    options?.available_locales,
    options?.default_locale,
  );
  const instrumentCode =
    options?.form_types?.find((ft) => ft.is_default)?.instrument_code ??
    "WHO_2022_VA";
  return {
    projectId: project.project_id,
    locale,
    enabledExtensions: [...(options?.enabled_extensions ?? [])],
    instrumentCode,
    translationVersion: options?.translation_versions?.[locale],
    intakeNote: options?.intake_note ?? null,
  };
}

function isDraftConfig(value: unknown): value is DraftConfig {
  if (!value || typeof value !== "object") return false;
  const config = value as Partial<DraftConfig>;
  return (
    typeof config.locale === "string" &&
    typeof config.projectId === "string" &&
    Array.isArray(config.enabledExtensions) &&
    config.enabledExtensions.every((entry) => typeof entry === "string") &&
    typeof config.instrumentCode === "string" &&
    (config.translationVersion === undefined ||
      typeof config.translationVersion === "number") &&
    (config.intakeNote === undefined ||
      config.intakeNote === null ||
      typeof config.intakeNote === "string") &&
    (!Object.prototype.hasOwnProperty.call(value, "smartva") || config.smartva === null || isSmartVaOptionsSnapshot(config.smartva))
  );
}

function withEnvelopeLocale(config: DraftConfig, value: unknown): DraftConfig {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("invalid_draft_envelope");
  }
  const envelope = value as Record<string, unknown>;
  const next = { ...config };
  if (Object.prototype.hasOwnProperty.call(envelope, "locale")) {
    if (typeof envelope.locale !== "string" || !UI_LOCALES.some(({ code }) => code === envelope.locale)) {
      throw new Error("invalid_draft_locale");
    }
    next.locale = envelope.locale;
  }
  if (Object.prototype.hasOwnProperty.call(envelope, "translation_version")) {
    if (
      typeof envelope.translation_version !== "number" ||
      !Number.isInteger(envelope.translation_version) ||
      envelope.translation_version < 0
    ) {
      throw new Error("invalid_draft_translation_version");
    }
    next.translationVersion = envelope.translation_version;
  }
  return next;
}

function definitionErrorMessage(error: unknown): string | undefined {
  if (error instanceof FormDefinitionError && error.code === "incompatible_engine") {
    return "Update the app to open this form. Your saved answers remain on this device.";
  }
  if (error instanceof PinnedDefinitionError) {
    if (error.code === "current_definition_unavailable") {
      return "The current form is unavailable. Reconnect and retry before starting an interview.";
    }
    return "This interview's original form could not be verified. Your answers remain on this device.";
  }
  if (error instanceof FormDefinitionError) {
    return "The questionnaire form could not be verified. Your answers remain on this device.";
  }
  if (error instanceof Error && error.name === "FormDefinitionHistoryError") {
    return "This interview's original form is unavailable. Your answers remain on this device.";
  }
  return undefined;
}

function mergeProjectPrefill(
  project: ProjectSettings | undefined,
  orgUnitId: string | null | undefined,
  registration: Prefill | undefined,
): Prefill | undefined {
  const policy = project?.prefill_policy as
    | {
        direct?: Prefill;
        units?: Record<string, Prefill>;
      }
    | undefined;
  const direct = policy?.direct;
  const unit = orgUnitId ? policy?.units?.[orgUnitId] : undefined;
  if (!direct && !unit && !registration) return undefined;
  return {
    ...((direct?.interviewer ?? unit?.interviewer ?? registration?.interviewer)
      ? {
          interviewer:
            direct?.interviewer ??
            unit?.interviewer ??
            registration?.interviewer,
        }
      : {}),
    ...((direct?.deceased ?? unit?.deceased ?? registration?.deceased)
      ? {
          deceased:
            registration?.deceased ?? unit?.deceased ?? direct?.deceased,
        }
      : {}),
    answers: {
      ...(direct?.answers ?? {}),
      ...(unit?.answers ?? {}),
      ...(registration?.answers ?? {}),
      ...(typeof unit?.answers?.Id10055 === "string" && typeof registration?.answers?.Id10055 === "string"
        ? { Id10055: joinResidence(unit.answers.Id10055, registration.answers.Id10055) }
        : {}),
    },
    lockedQuestionNames: [
      ...new Set([
        ...(direct?.lockedQuestionNames ?? []),
        ...(unit?.lockedQuestionNames ?? []),
        ...(registration?.lockedQuestionNames ?? []),
      ]),
    ],
  };
}

export default function Form() {
  const styles = useUiStyles();
  const whoTheme = useWhoFormTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{
    userId: string;
    draftId: string;
    projectId?: string;
    siteId?: string;
    orgUnitId?: string;
    deathId?: string;
    clientDeathId?: string;
  }>();
  const { accounts, activity, onBeforeLock, chooseUiLocale, reload, lockVersion, holdRefresh } =
    useAppState();
  useEffect(() => holdRefresh?.(), [holdRefresh]);
  const lockVersionRef = useRef(lockVersion);
  lockVersionRef.current = lockVersion;
  const account = useStableAccount(accounts.find((a) => a.user_id === params.userId));
  const draftId = UUID.test(params.draftId ?? "") ? params.draftId : undefined;
  const [loaded, setLoaded] = useState<Loaded | undefined>();
  const [locale, setLocale] = useState("en");
  const [instrument, setInstrument] = useState<
    InstrumentDefinition | undefined
  >();
  const [translationFallback, setTranslationFallback] = useState(false);
  const [message, setMessage] = useState("");
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [languageOpen, setLanguageOpen] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [confirmFinish, setConfirmFinish] = useState(false);
  const leaveGuard = useLeaveGuard();
  const toast = useToast();
  const shell = useShell();
  const [blockedReferenceData, setBlockedReferenceData] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const controller = useRef<WhoVaDraftController | undefined>(undefined);
  const session = useRef<WhoVaSession | undefined>(undefined);
  const loadGeneration = useRef(0);
  // Respondent consent (docs/policy/respondent-consent-notice-draft.md, "Phone flow"): the questionnaire opens
  // once a decision applies; a refusal (or missing settings) locks the covered questions empty.
  const [consentView, setConsentView] = useState<ConsentView>({ kind: "checking" });
  // The consent screen opened from the top bar to change the decision on file (the form is closed meanwhile).
  const [changingConsent, setChangingConsent] = useState(false);
  const [whoRefused, setWhoRefused] = useState(false);
  const [serverRefused, setServerRefused] = useState(false);
  const [refusalRecoveryError, setRefusalRecoveryError] = useState(false);
  const [refusalRecoveryAttempt, setRefusalRecoveryAttempt] = useState(0);
  const [refusalRecovered, setRefusalRecovered] = useState(false);
  const [confirmWhoGrant, setConfirmWhoGrant] = useState(false);
  const [refusalAge, setRefusalAge] = useState("");
  const [refusalSex, setRefusalSex] = useState("");
  // "Delete draft": offered only while the draft was never sent; `deleted` stops any later autosave re-creating the row.
  const [canDelete, setCanDelete] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const deleted = useRef(false);
  // Why the server (or the phone's own check) would not take this interview, shown above the questionnaire.
  const [refusal, setRefusal] = useState<SendRefusal | undefined>();
  // The "N problems" chip and the safe-area insets the form's own overlays (Sections drawer, problems list) need.
  const [problemCount, setProblemCount] = useState(0);
  const [welcomeDismissed, setWelcomeDismissed] = useState(false);
  const insets = useSafeAreaInsets();
  const serverProblems = useMemo(() => refusalProblems(refusal, t("refusalNotAcceptedNoReason")), [refusal]);

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let active = true;
    setLoaded(undefined);
    setInstrument(undefined);
    setBlockedReferenceData(false);
    setMessage("");
    setTranslationFallback(false);
    setWelcomeDismissed(false);
    controller.current = undefined;
    session.current = undefined;
    if (!account || !draftId) {
      return () => {
        active = false;
      };
    }
    void (async () => {
      let db: Db | undefined;
      try {
        db = await openInterviewerDb(account.user_id);
      } catch (error) {
        if (active && generation === loadGeneration.current) {
          if (
            error instanceof SessionRevokedError ||
            error instanceof SignInRequiredError
          ) {
            await reload();
            if (active && generation === loadGeneration.current) {
              router.replace("/");
            }
          } else {
            setBlockedReferenceData(true);
            setMessage(errorText(error));
          }
        }
        return;
      }
      if (!db || !active || generation !== loadGeneration.current) return;
      if (account.standalone) {
        // Path C: no server project, reference pack or definition fetch. The bundled instrument and the
        // standalone default extensions; the draft's own saved config wins on reopen.
        try {
          const projectId = standaloneProjectId(account.user_id);
          const [row, savedConfig, recall] = await Promise.all([
            getDraftRow(db, draftId),
            getMeta<DraftConfig>(db, draftConfigKey(draftId)),
            getMeta<InterviewerRecall>(db, RECALL_META_KEY),
          ]);
          if (row?.completed) {
            router.back();
            return;
          }
          let config: DraftConfig = isDraftConfig(savedConfig) && savedConfig.projectId === projectId
            ? savedConfig
            : { projectId, locale: "en", enabledExtensions: [...STANDALONE_DEFAULT_EXTENSIONS], instrumentCode: "WHO_2022_VA" };
          const definition = standaloneDefinition(config.enabledExtensions);
          const needsSmartVaSnapshot = !Object.prototype.hasOwnProperty.call(config, "smartva");
          if (needsSmartVaSnapshot) {
            const profile = await getOfflineProfile().catch(() => null);
            config = {
              ...config,
              smartva: await standaloneSmartVaSnapshot(profile, config.instrumentCode, definition.instrument.version),
            };
          }
          if (row) {
            const stored = await db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [draftId]);
            if (!stored) throw new Error("draft_missing");
            config = withEnvelopeLocale(config, JSON.parse(stored.envelope));
          }
          if (!row || needsSmartVaSnapshot) await setMeta(db, draftConfigKey(draftId), config);
          if (!active || generation !== loadGeneration.current) return;
          setLoaded({
            db,
            project: standaloneProject(projectId),
            config,
            definition,
            accessVersion: lockVersion,
            hasStartedSection: Boolean(row),
            recall,
            accountName: account.name,
            standalone: true,
            projectId,
            siteId: STANDALONE_SITE_ID,
            binding: { projectId },
          });
          setLocale(config.locale);
        } catch (error) {
          if (!active || generation !== loadGeneration.current) return;
          setBlockedReferenceData(true);
          setMessage(errorText(error));
        }
        return;
      }
      try {
        const [
          referenceData,
          localDraft,
          savedConfig,
          foundCase,
          registration,
        ] = await Promise.all([
          getCachedReferenceData(db),
          getDraftRow(db, draftId),
          getMeta<DraftConfig>(db, draftConfigKey(draftId)),
          params.deathId
            ? getCase(db, params.deathId)
            : Promise.resolve(undefined),
          params.clientDeathId
            ? getRegistration(db, params.clientDeathId)
            : Promise.resolve(undefined),
        ]);
        let existingDraft = localDraft;
        let caseDetail = foundCase;
        let draftConflict = false;
        let importedDraft = false;
        const hostProjectId =
          params.projectId ??
          existingDraft?.project_id ??
          foundCase?.project_id ??
          registration?.project_id;
        if (!hostProjectId) {
          setBlockedReferenceData(true);
          setMessage(t("referenceDataUnavailable"));
          return;
        }
        if (params.deathId) {
          try {
            caseDetail = await fetchCaseDetail(account.user_id, db, params.deathId, {
              expectedProjectId: hostProjectId,
            });
            if (!active || generation !== loadGeneration.current) return;
            const project = referenceData?.projects.find(
              ({ project: candidate }) => candidate.project_id === hostProjectId,
            )?.project;
            const reconciled = await reconcileCaseDraft(
              account.user_id,
              db,
              caseDetail,
              existingDraft,
              draftId,
              project ? draftSyncDefaults(project) : undefined,
            );
            existingDraft = reconciled.draft;
            draftConflict = reconciled.conflict;
            importedDraft = reconciled.imported;
            if (existingDraft && existingDraft.id !== draftId) {
              router.replace({
                pathname: "/form",
                params: { ...params, draftId: existingDraft.id },
              });
              return;
            }
          } catch (error) {
            // A saved interview can still be opened when only the network is unavailable.
            if (!(error instanceof TypeError) || !existingDraft) throw error;
            caseDetail = foundCase;
          }
          if (!active || generation !== loadGeneration.current) return;
        }
        let host = await resolveDraftHost(db, draftId, {
          ...params,
          projectId: hostProjectId,
        });
        if (!active || generation !== loadGeneration.current) return;
        if (
          !existingDraft &&
          params.deathId &&
          (!caseDetail || !caseDetail.prefill || !canStartDeathInterview(caseDetail.state))
        ) {
          router.back();
          return;
        }
        if (
          !existingDraft &&
          params.clientDeathId &&
          (!registration || registration.state !== "pending")
        ) {
          router.back();
          return;
        }
        if (!host || host === "completed") {
          router.back();
          return;
        }
        const project = referenceData?.projects.find(
          ({ project: candidate }) => candidate.project_id === hostProjectId,
        )?.project;
        if (
          params.clientDeathId &&
          registration &&
          referenceData?.bootstrap.user
        ) {
          const interviewer = {
            id: referenceData.bootstrap.user.user_id,
            name: referenceData.bootstrap.user.name,
          };
          const prefill = mergeProjectPrefill(
            project,
            registration.org_unit_id,
            prefillFromRegistration(registration.fields, interviewer),
          );
          host = { ...host, prefill, binding: { ...host.binding, prefill } };
        }
        if (!project) {
          setBlockedReferenceData(true);
          setMessage(t("referenceDataUnavailable"));
          return;
        }
        const hasSavedConfig =
          existingDraft &&
          isDraftConfig(savedConfig) &&
          savedConfig.projectId === hostProjectId;
        const hasServerBase = Boolean(
          existingDraft?.server_draft_id && existingDraft.base_updated_at,
        );
        if (
          (!referenceData && !hasSavedConfig) ||
          (existingDraft && !hasSavedConfig && !importedDraft && !hasServerBase)
        ) {
          setBlockedReferenceData(true);
          setMessage(t("referenceDataUnavailable"));
          return;
        }
        const newCollection =
          !existingDraft &&
          Boolean(params.siteId) &&
          !params.deathId &&
          !params.clientDeathId;
        const projectPack = referenceData?.projects.find(
          ({ project: candidate }) => candidate.project_id === hostProjectId,
        );
        const validDirectTarget = projectPack
          ? targetsFrom(projectPack.project, projectPack.units).some(
              (target) =>
                target.siteId === params.siteId &&
                (target.orgUnitId ?? undefined) ===
                  (params.orgUnitId ?? undefined),
            )
          : false;
        if (
          newCollection &&
          (!projectPack ||
            !startsDirectly(projectPack.project, params.siteId) ||
            !validDirectTarget)
        ) {
          setBlockedReferenceData(true);
          setMessage(t("referenceDataUnavailable"));
          return;
        }
        let config =
          isDraftConfig(savedConfig) && savedConfig.projectId === hostProjectId
            ? savedConfig
            : configFromReference(project!);
        const needsSmartVaSnapshot = !hasSavedConfig && !Object.prototype.hasOwnProperty.call(config, "smartva");
        if (needsSmartVaSnapshot) {
          const targets = (project as ProjectSettings & { smartva_targets?: SmartVaTarget[] }).smartva_targets;
          config = {
            ...config,
            smartva: projectSmartVaSnapshot(targets, { siteId: host.siteId, orgUnitId: host.orgUnitId }),
          };
        }
        const serverEnvelopeChanged = Boolean(
          existingDraft?.server_draft_id &&
            existingDraft.base_updated_at !== localDraft?.base_updated_at,
        );
        let envelope: Record<string, unknown> | undefined;
        if (importedDraft || hasServerBase) {
          const stored = await db.getFirstAsync<{ envelope: string }>(
            "SELECT envelope FROM drafts WHERE id = ?",
            [draftId],
          );
          if (!stored) throw new Error("draft_missing");
          try {
            const parsed = JSON.parse(stored.envelope) as unknown;
            if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
              throw new Error("invalid_draft_envelope");
            }
            envelope = parsed as Record<string, unknown>;
          } catch {
            throw new Error("invalid_draft_envelope");
          }
          config = withEnvelopeLocale(config, envelope);
        } else if (existingDraft) {
          const stored = await db.getFirstAsync<{ envelope: string }>(
            "SELECT envelope FROM drafts WHERE id = ?",
            [draftId],
          );
          if (!stored) throw new Error("draft_missing");
          const parsed = JSON.parse(stored.envelope) as unknown;
          if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
            throw new Error("invalid_draft_envelope");
          }
          envelope = parsed as Record<string, unknown>;
          config = withEnvelopeLocale(config, envelope);
        }
        const options = project.form_options as ProjectSettings["form_options"] & {
          narration_languages?: Array<{ code: string; label: string }>;
        };
        const narrationLanguageCodes = (options.narration_languages ?? []).map(
          ({ code }) => code,
        );
        const cache = createNativeDefinitionCache(
          db as Parameters<typeof createNativeDefinitionCache>[0],
          account.user_id,
        );
        await cache.initialize();
        if (!active || generation !== loadGeneration.current) return;
        const request = (path: string, requestOptions: { ifNoneMatch?: string }) =>
          authedRawRequest(account.user_id, path, {
            ifNoneMatch: requestOptions.ifNoneMatch,
            acceptGzip: true,
          });
        const bundledInstrument = createWhoVa2022Instrument(config.enabledExtensions);
        const definition = envelope
          ? await resolveSavedEnvelopeDefinition({
              accountId: account.user_id,
              projectId: hostProjectId,
              envelope,
              request,
              cache,
              narrationLanguageCodes,
              bundledLegacyDefinitions: [{
                instrument: bundledInstrument,
                instrumentVersion: bundledInstrument.version,
                extensions: config.enabledExtensions,
              }],
              legacyDefinitionExtensions: hasSavedConfig
                ? config.enabledExtensions
                : undefined,
            })
          : await resolveNewInterviewDefinition({
              accountId: account.user_id,
              projectId: hostProjectId,
              options: {
                instrumentVersion: project.form_options.instrument_version ?? null,
                definitionSha256: project.form_options.definition_sha256 ?? null,
                extensions: project.form_options.enabled_extensions ?? [],
              },
              request,
              cache,
              narrationLanguageCodes,
              bundledOriginal: {
                instrument: bundledInstrument,
                instrumentVersion: bundledInstrument.version,
                extensions: config.enabledExtensions,
              },
              canUseBundledFallback: () =>
                canUseBundledFallbackForProject(account.user_id, db!, hostProjectId),
              onServedDefinition: () =>
                markProjectDefinitionServed(account.user_id, db!, hostProjectId),
            });
        if (!active || generation !== loadGeneration.current) return;
        if (!hasSavedConfig || needsSmartVaSnapshot || importedDraft || draftConflict || serverEnvelopeChanged || hasServerBase) {
          await setMeta(db, draftConfigKey(draftId), config);
        }
        if (!active || generation !== loadGeneration.current) return;
        if (
          project &&
          !host.prefill &&
          (!params.deathId || !caseDetail) &&
          params.siteId
        ) {
          host = {
            ...host,
            prefill: mergeProjectPrefill(project, params.orgUnitId, undefined),
          };
        }
        const recall = await getMeta<InterviewerRecall>(db, RECALL_META_KEY);
        if (!active || generation !== loadGeneration.current) return;
        const hasStartedSection = Boolean(existingDraft && (!envelope || envelope.currentSection));
        setLoaded({
          db,
          project: project!,
          config,
          definition,
          accessVersion: lockVersion,
          hasStartedSection,
          recall,
          accountName: referenceData?.bootstrap.user?.name,
          ...host,
        });
        setLocale(config.locale);
      } catch (error) {
        if (!active || generation !== loadGeneration.current) return;
        if (
          error instanceof SessionRevokedError ||
          error instanceof SignInRequiredError
        ) {
          await reload();
          if (active && generation === loadGeneration.current) {
            router.replace("/");
          }
          return;
        }
        setBlockedReferenceData(true);
        setMessage(definitionErrorMessage(error) ?? errorText(error));
      }
    })();
    return () => {
      active = false;
    };
    // params is a new object each render; its fields are the dependencies.
  }, [
    account,
    draftId,
    params.siteId,
    params.orgUnitId,
    params.deathId,
    params.clientDeathId,
    lockVersion,
    router,
    loadAttempt,
  ]);

  const baseInstrument = loaded?.definition.instrument;

  // The decision that applies to this interview: its own, its registration's, else the project's settings.
  useEffect(() => {
    setConsentView({ kind: "checking" });
    setRefusal(undefined);
    if (!loaded || !draftId) return undefined;
    let live = true;
    void (async () => {
      let row = await getDraftRow(loaded.db, draftId);
      if (row?.upload_issue === "refusal_stale") {
        try {
          if (!account) throw new Error("refusal_server_draft_unavailable");
          await recoverRefusalDraft(account.user_id, loaded.db, row);
          row = await getDraftRow(loaded.db, draftId);
          setLoaded((current) => current ? { ...current, prefill: undefined, binding: { ...current.binding, prefill: undefined } } : current);
          if (live) { setRefusalRecovered(true); setRefusalRecoveryError(false); }
        } catch {
          if (live) setRefusalRecoveryError(true);
          return;
        }
      }
      const saved = await loaded.db.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [draftId]);
      const answers = saved ? (JSON.parse(saved.envelope) as { data?: Record<string, unknown> }).data : undefined;
      if (live) {
        setServerRefused(row?.upload_issue === "consent_refused");
        setWhoRefused(answers?.Id10013 === "no");
        setRefusalAge(typeof answers?.refusal_age_group === "string" ? answers.refusal_age_group : "");
        setRefusalSex(typeof answers?.refusal_sex === "string" ? answers.refusal_sex : "");
      }
      const applied = await consentForDraft(loaded.db, {
        id: draftId,
        death_id: row?.death_id ?? loaded.binding.deathId,
        client_death_id: row?.client_death_id ?? loaded.binding.clientDeathId,
      });
      if (isRefused(answers, applied?.record.envelope.decision)) await clearRefusedDraft(loaded.db, draftId);
      const last = await sendRefusal(loaded.db, draftId);
      // The server refused the decision this draft inherited: ask for a new attempt-level one.
      const inheritedRefused = applied && !applied.own && await inheritedConsentRefused(loaded.db, draftId);
      let gateConfig: ProjectConsentConfig | undefined;
      if (loaded.standalone) {
        const profile = await getOfflineProfile().catch(() => null);
        gateConfig = (await standaloneConsentConfigWithSavedNotice(loaded.projectId, loaded.config.locale, { organisation: profile?.facility_name })) ?? undefined;
        if (!gateConfig && !applied) {
          if (live) setConsentView({ kind: "blocked" });
          return;
        }
      } else {
        gateConfig = await getConsentConfig(loaded.db, loaded.projectId);
      }
      const gate = interviewConsentGate(gateConfig);
      if (!live) return;
      setRefusal(last?.message || last?.status === 422 ? last : undefined);
      const config = gate.state === "ask" ? gate.config : gate.state === "off" ? gateConfig : undefined;
      if (applied && !inheritedRefused) {
        const refused = applied.record.envelope.decision === "refused";
        setConsentView({ kind: "ready", covered: refused ? applied.record.covered_fields : [], decision: refused ? "refused" : "granted", required: gate.state !== "off", config });
        return;
      }
      if (gate.state === "ask") setConsentView({ kind: "ask", config: gate.config });
      else if (gate.state === "off") setConsentView({ kind: "ready", covered: [], decision: "none", required: false });
      else {
        recordError("consent settings unavailable");
        setConsentView({ kind: "ready", covered: gate.covered, unavailable: true, decision: "none", required: true });
      }
    })().catch(() => {
      if (live) setConsentView({ kind: "ready", covered: [...DEFAULT_COVERED_FIELDS], unavailable: true, decision: "none", required: true });
    });
    return () => { live = false; };
  // eslint-disable-next-line react-hooks/exhaustive-deps -- a language switch re-creates `loaded`; consent is decided once per interview
  }, [loaded?.db, loaded?.projectId, draftId, refusalRecoveryAttempt]);

  // Delete draft is offered while the draft was never sent (the store checks again when it deletes).
  useEffect(() => {
    if (!loaded || !draftId || canDelete || saveState !== "saved") return undefined;
    let live = true;
    void isNeverSentDraft(loaded.db, draftId).then((never) => live && setCanDelete(never)).catch(() => undefined);
    return () => { live = false; };
  }, [loaded, draftId, canDelete, saveState]);

  useEffect(() => {
    if (!loaded || !baseInstrument || !account) return;
    let active = true;
    const code = loaded.config.instrumentCode;
    const version = loaded.config.translationVersion;
    void (async () => {
      try {
        // Standalone uses only its version-pinned APK pack and SQLite cache.
        const standalonePack = loaded.standalone
          ? await standaloneTranslationsForDraft(loaded.db, loaded.project.project_id, code, locale, version)
          : undefined;
        const translations = loaded.standalone
          ? standalonePack!.translations
          : await translationsForDraft(
              account.user_id,
              loaded.db,
              loaded.project.project_id,
              code,
              locale,
              version,
              loaded.project.form_options.translation_versions?.[locale],
            );
        if (!active) return;
        await chooseUiLocale(locale);
        setTranslationFallback(standalonePack?.partial ?? (locale !== "en" && !translations));
        setInstrument(applyTranslations(baseInstrument, translations ?? null, locale));
        setMessage("");
      } catch (error) {
        if (
          error instanceof SessionRevokedError ||
          error instanceof SignInRequiredError
        ) {
          await reload();
          if (active) router.replace("/");
          return;
        }
        if (active) {
          await chooseUiLocale(locale);
          setInstrument(undefined);
          setMessage(errorText(error));
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [loaded, baseInstrument, locale, account, chooseUiLocale, reload, router]);

  // Save when the app leaves the foreground: Android may kill it there.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active")
        void controller.current
          ?.saveDraft()
          .catch((error: unknown) => setMessage(errorText(error)));
    });
    return () => subscription.remove();
  }, []);

  // Locking saves the open draft before the database closes.
  useEffect(
    () =>
      onBeforeLock(async () => void (await controller.current?.saveDraft())),
    [onBeforeLock],
  );

  // Autosaves count as activity, so typing a long answer never trips the idle lock.
  const draftStore = useMemo(() => {
    if (!loaded || loaded.accessVersion !== lockVersion || !draftId) return undefined;
    const store = createDraftStore(loaded.db, {
      projectId: loaded.projectId,
      siteId: loaded.siteId,
      orgUnitId: loaded.orgUnitId,
      binding: loaded.binding,
      locale: loaded.config.locale,
      translationVersion: loaded.config.translationVersion,
      definitionPin: loaded.definition.pin,
    });
    let configSaved = false;
    const writeLatest = coalesceLatest(async (draft: Parameters<typeof store.save>[0]) => {
      // Keep the questionnaire choices with the encrypted draft so a later
      // pack refresh cannot silently change its language or modules. Once per
      // mount: they cannot change while the form is open (digitva-wh4w).
      if (!configSaved) {
        await setMeta(loaded.db, draftConfigKey(draftId), loaded.config);
        configSaved = true;
      }
      // Remember the interviewer's own details for the next interview.
      const recall = recallFromData(draft.data);
      if (recall && recallChanged(loaded.recall, recall)) {
        await setMeta(loaded.db, RECALL_META_KEY, recall);
        loaded.recall = recall;
      }
      return store.save(draft);
    });
    return {
      ...store,
      save: (draft: Parameters<typeof store.save>[0]) => {
        if (deleted.current) return Promise.resolve(); // the draft was deleted: nothing may bring its row back
        if (loaded.accessVersion !== lockVersionRef.current) {
          return Promise.reject(new Error("interview_access_changed"));
        }
        activity();
        return writeLatest(draft);
      },
    };
  }, [loaded, draftId, activity, lockVersion]);

  // A stored draft replaces these on mount (the form's restore), so they only fill a new one.
  const covered = consentView.kind === "ready" ? consentView.covered : [];
  const initialData = useMemo(() => {
    if (!loaded) return undefined;
    const data = withInterviewerRecall(initialDataFromPrefill(loaded.prefill), loaded.recall, loaded.accountName);
    return covered.length ? withoutCovered(data, covered) : data;
  }, [loaded, covered]);
  const lockedNames = useMemo(
    () => (covered.length ? [...new Set([...(loaded?.prefill?.lockedQuestionNames ?? []), ...covered])] : loaded?.prefill?.lockedQuestionNames),
    [loaded, covered],
  );

  // Audio, photographs and documents (docs/policy/phone-attachments.md). Files go up ahead of the interview;
  // a direct start (no case) is named to the server by its draft id.
  const attachmentServices = useAttachmentServices({
    db: loaded?.db,
    draftId,
    projectId: loaded?.projectId ?? null,
  });
  const formServices = useMemo(() => ({ ...platformServices, ...attachmentServices }), [attachmentServices]);

  // With the questionnaire open, a message is a toast so the form never shifts; the blocked screens below show it in place.
  const editorShown = Boolean(loaded && instrument && draftStore && !blockedReferenceData);
  useEffect(() => {
    if (!message || !editorShown) return;
    toast.show({ kind: "error", text: message });
    setMessage("");
  }, [message, editorShown, toast]);

  if (loaded && loaded.accessVersion !== lockVersion) {
    return <ActivityIndicator style={{ flex: 1 }} />;
  }
  if (!account || !draftId) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return (
      <Redirect
        href={{ pathname: "/unlock", params: { userId: account.user_id } }}
      />
    );
  }
  if (blockedReferenceData) {
    return (
      <Screen title={t("appName")}>
        <Text style={styles.error}>{message}</Text>
        <Button
          kind="secondary"
          label={t("refresh")}
          onPress={() => setLoadAttempt((attempt) => attempt + 1)}
        />
        <Button
          kind="secondary"
          label={t("cancel")}
          onPress={() => router.back()}
        />
      </Screen>
    );
  }
  if (!loaded || !draftStore) return <ActivityIndicator style={{ flex: 1 }} />;
  if (refusalRecoveryError) return <Screen title={t("appName")}><Text style={styles.error} accessibilityRole="alert">{locale.startsWith("hi") ? "सर्वर से इनकार की स्थिति नहीं मिल सकी। इंटरनेट जाँचें और फिर प्रयास करें।" : "Could not refresh the server's refusal. Check the connection and try again."}</Text><Button label={t("retry")} onPress={() => { setRefusalRecoveryError(false); setRefusalRecoveryAttempt((n) => n + 1); }} /><Button kind="secondary" label={t("cancel")} onPress={() => router.back()} /></Screen>;
  if (!instrument) {
    return (
      <Screen title={t("appName")}>
        <Text style={styles.error}>
          {message || t("questionnaireLanguageUnavailable")}
        </Text>
        <Button
          kind="secondary"
          label={t("cancel")}
          onPress={() => router.back()}
        />
      </Screen>
    );
  }

  // The first decision (before the questionnaire opens), or a change of the one on file from the top bar.
  const askConfig = consentView.kind === "ask" ? consentView.config : changingConsent && consentView.kind === "ready" ? consentView.config : undefined;
  if (askConfig) {
    const config = askConfig;
    const changing = consentView.kind === "ready";
    const recordConsent = async (envelope: ConsentRecordEnvelope) => {
      try {
        const record = storedConsent(envelope, config, account!.user_id);
        // Replaces the decision on file: only this record travels with the interview (the server keeps the newest).
        await saveDraftConsent(loaded!.db, draftId!, record);
        if (envelope.decision === "granted" && (serverRefused || (changing && consentView.kind === "ready" && consentView.decision === "refused"))) {
          await setMeta(loaded!.db, `consent:resume-who:${draftId}`, true);
        }
        if (envelope.decision === "refused") {
          setLoaded((current) => current ? { ...current, prefill: undefined, binding: { ...current.binding, prefill: undefined } } : current);
        }
        if (loaded!.standalone) {
          // The exact text the respondent saw travels with the record on the later push (contract section 17).
          const notice = config.notice_versions.find((version) => version.notice_version_id === envelope.notice_version_id) as
            | (typeof config.notice_versions[number] & { bundle_version?: string; bundle_sha256?: string }) | undefined;
          if (!notice?.bundle_version || !notice.bundle_sha256) throw new Error("standalone_notice_unknown");
          await saveStandaloneConsent(loaded!.db, draftId!, {
            envelope, notice_text: notice.text, bundle_version: notice.bundle_version, bundle_sha256: notice.bundle_sha256,
          });
        }
        // A refusal takes the covered answers off the stored draft and its prefill now, not only in memory.
        if (envelope.decision === "refused") await stripDraftCovered(loaded!.db, draftId!, record.covered_fields);
        const granted = envelope.decision !== "refused";
        setConsentView({
          kind: "ready", covered: granted ? [] : record.covered_fields, decision: granted ? "granted" : "refused", required: true, config,
        });
        setChangingConsent(false);
        if (granted && serverRefused) { setServerRefused(false); setWhoRefused(true); }
        toast.show({
          kind: granted ? "success" : "info",
          text: t(changing ? (granted ? "consentChangedAgreed" : "consentChangedRefused") : granted ? "consentRecordedForInterview" : "consentRefusedInterview"),
        });
      } catch (error) {
        toast.show({ kind: "error", text: errorText(error) });
      }
    };
    return (
      <Screen title={t("consentHeading")}>
        <RespondentConsentPanel config={config} language={locale} clientDraftId={draftId!} makeId={randomUUID} onDecision={(envelope) => void recordConsent(envelope)} />
        <Button kind="secondary" label={t("cancel")} onPress={() => (changing ? setChangingConsent(false) : router.back())} />
      </Screen>
    );
  }
  if (consentView.kind === "blocked") {
    return (
      <Screen title={t("consentHeading")}>
        <Text accessibilityRole="alert" style={styles.error}>{t("standaloneConsentUnavailable")}</Text>
        <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
      </Screen>
    );
  }
  if (consentView.kind !== "ready") return <ActivityIndicator style={{ flex: 1 }} />;

  if (whoRefused || serverRefused || consentView.decision === "refused") {
    const saveRefusal = async () => {
      try {
        const now = new Date().toISOString();
        const existing = await draftStore.load?.(draftId);
        const data = refusalAnswers({ ...(existing?.data ?? {}), ...(whoRefused ? { Id10013: "no" } : {}), refusal_age_group: refusalAge, refusal_sex: refusalSex }) as SubmissionData;
        await draftStore.save(existing ? { ...existing, updatedAt: now, data } : {
          schemaVersion: 1, formVersion: WHO_VA_FORM_VERSION, id: draftId, instrumentId: instrument.id,
          instrumentVersion: instrument.version, currentSection: instrument.sections[0].name, createdAt: now, updatedAt: now, data,
        });
        await markCompleted(loaded.db, draftId, { valid: true, issues: [] });
        leaveGuard.release();
        router.back();
      } catch (error) { setMessage(errorText(error)); }
    };
    const changeRefusal = async () => {
      if (serverRefused || consentView.decision === "refused") {
        if (consentView.config) setChangingConsent(true);
        else setMessage(t("consentUnavailableInterview"));
        return;
      }
      setConfirmWhoGrant(true);
    };
    const grantWhoConsent = async () => {
      try {
        await controller.current?.saveDraft();
        await clearRefusedDraft(loaded.db, draftId);
        await runInTransaction(loaded.db, async (tx) => {
          const row = await tx.getFirstAsync<{ envelope: string }>("SELECT envelope FROM drafts WHERE id = ?", [draftId]);
          if (row) {
            const draft = JSON.parse(row.envelope) as { data: Record<string, unknown> };
            draft.data = { Id10013: "yes" };
            const result = await tx.runAsync("UPDATE drafts SET envelope = ?, completed = 0, completion = NULL, upload_issue = NULL, draft_sync_dirty = 1 WHERE id = ? AND envelope = ?", [JSON.stringify(draft), draftId, row.envelope]);
            if (!result || typeof result !== "object" || !("changes" in result) || Number(result.changes) !== 1) throw new Error("draft_conflict");
            await setMeta(tx, `consent:resume-who:${draftId}`, true);
          }
        });
        setLoaded((current) => current ? { ...current, prefill: undefined, binding: { ...current.binding, prefill: undefined } } : current);
        setWhoRefused(false);
        setConfirmWhoGrant(false);
      } catch (error) { setMessage(errorText(error)); }
    };
    return <Screen title={t("appName")}>{refusalRecovered ? <Text style={styles.text}>{locale.startsWith("hi") ? "सर्वर पर इनकार दर्ज है। पुराने उत्तर हटा दिए गए हैं; आगे बढ़ने के लिए सहमति की फिर पुष्टि करें।" : "The server recorded a refusal. Previous answers were removed; confirm consent again to continue."}</Text> : null}<RefusalPanel locale={locale} age={refusalAge} sex={refusalSex} onAge={setRefusalAge} onSex={setRefusalSex} onSave={() => void saveRefusal()} onChangeConsent={() => void changeRefusal()} onNew={() => { leaveGuard.release(); router.back(); }} />{confirmWhoGrant ? <ConfirmDialog title={locale.startsWith("hi") ? "सहमति की पुष्टि करें" : "Confirm consent"} message={locale.startsWith("hi") ? "क्या उत्तरदाता ने अब साक्षात्कार के लिए सहमति दी है? हटाए गए उत्तर वापस नहीं आएंगे।" : "Has the respondent now agreed to the interview? Removed answers will not be restored."} confirmLabel={locale.startsWith("hi") ? "हाँ, सहमति दी" : "Yes, consent granted"} cancelLabel={t("cancel")} onConfirm={() => void grantWhoConsent()} onCancel={() => setConfirmWhoGrant(false)} /> : null}{message ? <Text style={styles.error}>{message}</Text> : null}</Screen>;
  }

  const intakeNote = (loaded.config.intakeNote ?? loaded.project.form_options?.intake_note ?? "").trim();
  const showWelcome =
    !welcomeDismissed &&
    !loaded.hasStartedSection &&
    loaded.config.enabledExtensions.includes("intake_screen") &&
    Boolean(intakeNote);
  if (showWelcome) {
    return (
      <Screen title={t("beforeYouBegin")} variant="immersive">
        <View testID="native-interview-welcome-card" style={[styles.card, { margin: 16, gap: 12 }]}>
          <Text style={styles.headline}>{t("beforeYouBegin")}</Text>
          <Text style={styles.text}>{intakeNote}</Text>
          <Button label={t("startQuestionnaire")} onPress={() => setWelcomeDismissed(true)} />
          <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  /** Save what is typed, then close the questionnaire for the consent screen (its answers come back from the stored draft). */
  async function changeConsent() {
    try {
      await controller.current?.saveDraft();
    } catch (error) {
      setMessage(errorText(error));
      return;
    }
    controller.current = undefined;
    session.current = undefined;
    setChangingConsent(true);
  }

  /** Delete this never-sent draft with its consent record and files, then back to the worklist. */
  async function deleteThisDraft() {
    setConfirmDelete(false);
    deleted.current = true;
    try {
      if (!(await deleteUnsentDraft(loaded!.db, draftId!))) throw new Error("draft_not_deletable");
    } catch {
      deleted.current = false;
      setCanDelete(false);
      toast.show({ kind: "error", text: t("deleteDraftFailed") });
      return;
    }
    toast.show({ kind: "success", text: t("deleteDraftDone") });
    router.replace(account!.standalone
      ? { pathname: "/standalone", params: { userId: account!.user_id } }
      : { pathname: "/worklist", params: { userId: account!.user_id, view: "interviews", filter: "drafts" } });
  }

  /** Flush first; a failed save asks before leaving so typed answers are never dropped silently. */
  async function leave() {
    try {
      await controller.current?.saveDraft();
    } catch (error) {
      setSaveState("unsaved");
      setMessage(errorText(error));
      setConfirmLeave(true);
      return;
    }
    leaveGuard.release();
    router.back();
  }
  leaveGuard.handler.current = () => void leave();

  async function saveNow() {
    setSaveState("saving");
    try {
      await controller.current?.saveDraft();
      setSaveState("saved");
      toast.show({ kind: "success", text: t("draftSaved") });
    } catch (error) {
      setSaveState("unsaved");
      setMessage(errorText(error));
    }
  }

  async function switchLocale(code: string) {
    try {
      await controller.current?.saveDraft();
    } catch (error) {
      setMessage(errorText(error));
      return;
    }
    setLoaded((current) => {
      if (!current) return current;
      return {
        ...current,
        config: {
          ...current.config,
          locale: code,
          translationVersion:
            current.definition.pin &&
            current.definition.pin.instrumentVersion !== current.project.form_options.instrument_version
              ? undefined
              : current.project.form_options?.translation_versions?.[code] ??
                (current.standalone ? standaloneTranslationVersion(code) : undefined),
        },
      };
    });
    setLocale(code);
  }

  async function complete(result: SubmissionValidationResult, autoRunSmartVa = true) {
    if (!loaded || !draftId) return;
    const completion = { valid: result.valid, issues: result.issues };
    if (!isUploadable(result.data, completion)) {
      setMessage(t("finishNeedsOutcome"));
      return;
    }
    // What the server checks on a direct start, with its messages: a failing interview stays a draft.
    const issues = preSendIssues(result.data, {
      valid: result.valid,
      direct: !loaded.binding.deathId && !loaded.binding.clientDeathId,
    });
    if (issues.length) {
      recordError(`precheck ${issues.map((issue) => issue.message).join(",")}`);
      setRefusal({
        ref: "precheck",
        message: issues.map((issue) => t(issue.message)).join("\n"),
        fields: [...new Set(issues.flatMap((issue) => issue.fields))],
        at: new Date().toISOString(),
      });
      controller.current?.showProblems();
      return;
    }
    try {
      await controller.current?.saveDraft();
      try {
        await recordDraftTimeline(loaded.db, draftId, "submit_started");
      } catch {
        // The answer save is already durable; a concurrent milestone write must not strand it.
      }
      await markCompleted(loaded.db, draftId, completion);
      if (autoRunSmartVa && completion.valid && !isRefused(result.data, consentView.kind === "ready" ? consentView.decision : undefined)) {
        void ensureLocalSmartVa({ db: loaded.db, userId: account!.user_id, draftId }).catch(() => undefined);
      }
      await clearSendError(loaded.db, draftId);
    } catch (error) {
      // Stay on the form with the answers intact; say what went wrong (digitva-jish).
      setMessage(error instanceof Error && error.message === "draft_conflict" ? t("formDraftConflict") : errorText(error));
      return;
    }
    leaveGuard.release();
    router.back();
  }

  /** Finish without the form's own "complete": allowed for an incomplete outcome only. */
  function finishIncomplete() {
    const result = session.current?.validate();
    if (result) void complete(result, false);
  }

  const locales = questionnaireLocales(
    loaded.project.form_options?.available_locales,
  );
  const menuItems: SheetItem[] = [
    { key: "finish", label: t("finishIncomplete"), onPress: () => setConfirmFinish(true) },
    ...(locales.length > 1 ? [{ key: "language", label: t("questionnaireLanguage"), onPress: () => setLanguageOpen(true) }] : []),
    { key: "help", label: t("formHelp"), onPress: () => shell.openSheet("help") },
    { key: "preview", label: t("formPreviewAnswers"), onPress: () => controller.current?.openPreview() },
    { key: "save", label: t("saveNow"), onPress: () => void saveNow() },
    ...(consentView.required && consentView.config ? [{ key: "consent", label: t("consentChangeDecision"), onPress: () => void changeConsent() }] : []),
    ...(canDelete ? [{ key: "delete", label: t("deleteDraft"), onPress: () => setConfirmDelete(true) }] : []),
  ];
  const consentChip = consentView.required
    ? {
        label: t(consentView.decision === "granted" ? "consentChipAgreed" : "consentChipNotRecorded"),
        decision: consentView.decision,
        ...(consentView.config ? { onPress: () => void changeConsent() } : {}),
      }
    : undefined;
  return (
    <Screen title={t("appName")} variant="immersive">
      <FormTopBar
        title={revisionName({ prefill: loaded.prefill }) ?? t("appName")}
        saveState={saveState}
        onBack={() => void leave()}
        menuItems={menuItems}
        problemCount={problemCount}
        onProblems={() => controller.current?.showProblems()}
        consentChip={consentChip}
      />
      {confirmLeave ? (
        <ConfirmDialog
          title={t("leaveUnsavedTitle")}
          message={t("leaveUnsavedMessage")}
          confirmLabel={t("leaveAnyway")}
          cancelLabel={t("stay")}
          onConfirm={() => { setConfirmLeave(false); leaveGuard.release(); router.back(); }}
          onCancel={() => setConfirmLeave(false)}
        />
      ) : null}
      {confirmFinish ? (
        <ConfirmDialog
          title={t("finishIncompleteTitle")}
          message={t("finishIncompleteMessage")}
          confirmLabel={t("finishIncomplete")}
          cancelLabel={t("stay")}
          onConfirm={() => { setConfirmFinish(false); finishIncomplete(); }}
          onCancel={() => setConfirmFinish(false)}
        />
      ) : null}
      {confirmDelete ? (
        <ConfirmDialog
          destructive
          title={t("deleteDraftTitle")}
          message={t("deleteDraftMessage")}
          confirmLabel={t("deleteDraft")}
          onConfirm={() => void deleteThisDraft()}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : null}
      {translationFallback ? <Text style={[styles.muted, { paddingHorizontal: 16 }]} numberOfLines={1} testID={loaded.standalone ? "standalone-translation-fallback" : undefined}>{t(loaded.standalone ? "questionnairePartialEnglishFallback" : "questionnaireEnglishFallback")}</Text> : null}
      {consentView.unavailable ? <Text style={[styles.muted, { paddingHorizontal: 16 }]} testID="consent-unavailable">{t("consentUnavailableInterview")}</Text> : null}
      <Sheet
        visible={languageOpen}
        title={t("questionnaireLanguage")}
        onClose={() => setLanguageOpen(false)}
        items={locales.map((entry) => ({ key: entry.code, label: entry.label, selected: entry.code === locale, onPress: () => void switchLocale(entry.code) }))}
      />
      <View style={{ flex: 1 }}>
        <WhoVaForm
          theme={whoTheme}
          key={`${locale}:${covered.length}`}
          instrument={instrument}
          locale={locale}
          showEnglish={locale !== "en"}
          draftId={draftId}
          draftStore={draftStore}
          {...(initialData ? { initialData } : {})}
          {...(lockedNames ? { lockedQuestionNames: lockedNames } : {})}
          platform={formServices}
          condensePrompts
          compactFooter
          safeInsets={{ top: insets.top, bottom: insets.bottom }}
          {...(serverProblems ? { serverProblems } : {})}
          onProblemsChange={setProblemCount}
          onChange={(data) => {
            if (isRefused(data)) {
              setWhoRefused(true);
              void controller.current?.saveDraft().catch((error: unknown) => setMessage(errorText(error)));
            }
          }}
          autoSaveDraftOnChange
          onDraftController={(next) => {
            if (loaded.accessVersion === lockVersionRef.current) {
              controller.current = next;
            }
          }}
          onReady={(next) => {
            if (loaded.accessVersion === lockVersionRef.current) {
              session.current = next;
              // A saved draft may hold covered answers from before the refusal: they are dropped, not sent.
              const held = next.getSnapshot().data;
              if (covered.some((name) => name in held)) {
                next.replaceData(withoutCovered(held, covered));
                if (draftId) void deleteCoveredAttachments(loaded.db, draftId, covered).catch(() => undefined);
                void controller.current?.saveDraft().catch(() => undefined);
              }
            }
          }}
          onDraftError={(error) => {
            // The failure code only (e.g. draft_conflict); describeError scrubs the rest, and answers never reach it.
            recordError(`draft ${describeError(error)}`);
            setSaveState("unsaved");
            setMessage(t("errGeneric"));
          }}
          onDraftSaved={() => {
            setSaveState("saved");
            if (typeof recordDraftMilestones === "function") {
              void recordDraftMilestones(
                loaded.db,
                draftId,
                loaded.definition.instrument.sections.map((section) => section.name),
              ).catch(() => undefined);
            }
          }}
          onComplete={(result) => void complete(result)}
        />
      </View>
    </Screen>
  );
}
