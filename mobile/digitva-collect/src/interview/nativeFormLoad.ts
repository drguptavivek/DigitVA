/**
 * Opening one draft on the phone interview screen (src/nativeRoutes/form.tsx): its questionnaire config, form
 * definition, host and prefill, from the encrypted store and the cached reference pack. Moved out of the screen's
 * load effect with its steps, their order and their staleness checks unchanged; the effect keeps the reset, the
 * database open and the error handling. Native only (the encrypted SQLite store).
 */
import { createWhoVa2022Instrument } from "@drguptavivek/who-2022-va";
import type { useRouter } from "expo-router";

import type { Account } from "../auth";
import { authedRawRequest, trainingProjectFor } from "../auth";
import {
  getCase,
  getRegistration,
  joinResidence,
  prefillFromRegistration,
  resolveDraftHost,
  type DraftHost,
  type Prefill,
} from "../cases";
import { canStartDeathInterview } from "../deathWorkflow";
import { getDraftRow, getMeta, setMeta, type Db } from "../drafts";
import { reconcileCaseDraft } from "../draftSync";
import { createNativeDefinitionCache } from "../formDefinitionCache";
import {
  resolveNewInterviewDefinition,
  resolveSavedEnvelopeDefinition,
  type ResolvedInstrument,
} from "../formDefinitionRuntime";
import { isLocaleCode, questionnaireDefault, t } from "../i18n";
import { RECALL_META_KEY, type InterviewerRecall } from "../interviewerRecall";
import { getOfflineProfile, profileInterviewerAnswers, standaloneProfileMissing, standalonePrefill } from "../offlineProfile";
import { standaloneProfileMissingText } from "../offlineProfileForm";
import { isSmartVaOptionsSnapshot, projectSmartVaSnapshot, standaloneSmartVaSnapshot, type SmartVaOptionsSnapshot, type SmartVaTarget } from "../smartva/options";
import { STANDALONE_DEFAULT_EXTENSIONS } from "../standalone/config";
import { STANDALONE_SITE_ID, standaloneDefinition, standaloneDraftMismatch, standaloneProject, standaloneProjectId } from "../standalone/project";
import {
  canUseBundledFallbackForProject,
  draftSyncDefaults,
  fetchCaseDetail,
  getCachedReferenceData,
  markProjectDefinitionServed,
  startsDirectly,
  targetsFrom,
  type ProjectSettings,
} from "../sync";
import { scopeFor } from "../training";
import { readLocalEnvelope, readServerBasedEnvelope, readStandaloneDraftRow } from "./formDraftSql";

type Router = ReturnType<typeof useRouter>;

export interface Loaded extends DraftHost {
  db: Db;
  project: ProjectSettings;
  config: DraftConfig;
  definition: ResolvedInstrument;
  accessVersion: number;
  hasStartedSection: boolean;
  /** The interviewer's own details from their last interview (src/interviewerRecall.ts). */
  recall?: InterviewerRecall;
  /** The interviewer's profile answers, which outrank the recall (owner decision 2026-11-14). */
  profileAnswers?: InterviewerRecall;
  accountName?: string;
  /** Path C: no server project; the bundled form, the bundled consent notice, local translations only. */
  standalone?: boolean;
  /**
   * Standalone draft made on a different questionnaire than the bundled one (digitva-5bzf.12): its stored answers,
   * shown read-only. The form never mounts, so nothing is edited, completed or saved over them.
   */
  readOnlyData?: Record<string, unknown>;
}

export interface DraftConfig {
  projectId: string;
  locale: string;
  enabledExtensions: string[];
  instrumentCode: string;
  translationVersion?: number;
  intakeNote?: string | null;
  /** Exact SmartVA form/site options captured at draft creation; null freezes a missing target. */
  smartva?: SmartVaOptionsSnapshot | null;
}

/** The form route's search params (a type alias: expo-router's params constraint needs an index signature). */
export type FormRouteParams = {
  userId: string;
  draftId: string;
  projectId?: string;
  siteId?: string;
  orgUnitId?: string;
  deathId?: string;
  clientDeathId?: string;
};

/** What a load needs from the screen, and how it reports. */
export interface FormLoadContext {
  db: Db;
  account: Account;
  draftId: string;
  params: FormRouteParams;
  lockVersion: number;
  router: Router;
  /** False once the screen left or a newer load began; checked wherever the screen's effect always checked it. */
  isCurrent(): boolean;
  setLoaded(loaded: Loaded): void;
  setLocale(locale: string): void;
  setTrainingDraft(training: boolean): void;
  /** Show `message` with Refresh and Cancel instead of the questionnaire. */
  block(message: string): void;
}

export const draftConfigKey = (draftId: string) => `draft-config:${draftId}`;

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

export function isDraftConfig(value: unknown): value is DraftConfig {
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
    if (!isLocaleCode(envelope.locale)) {
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

export function mergeProjectPrefill(
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

/**
 * Path C: no server project, reference pack or definition fetch. The bundled instrument and the standalone default
 * extensions; the draft's own saved config wins on reopen. Rejects on a store or parse failure.
 */
export async function loadStandaloneDraft(context: FormLoadContext): Promise<void> {
  const { db, account, draftId, lockVersion, router } = context;
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
  const profile = !row || needsSmartVaSnapshot ? await getOfflineProfile().catch(() => null) : null;
  // A new interview starts only from a complete profile, which it prefills and locks (digitva-0vz7);
  // nothing is written for it. A draft with a row opens as before, with the prefill it started from.
  let prefill: Prefill | undefined;
  if (!row) {
    const missing = standaloneProfileMissing(profile);
    if (missing.length) {
      if (!context.isCurrent()) return;
      context.block(standaloneProfileMissingText(missing));
      return;
    }
    prefill = standalonePrefill(profile!);
  }
  if (needsSmartVaSnapshot) {
    config = {
      ...config,
      smartva: await standaloneSmartVaSnapshot(profile, config.instrumentCode, definition.instrument.version),
    };
  }
  if (row) {
    const stored = await readStandaloneDraftRow(db, draftId);
    if (!stored) throw new Error("draft_missing");
    const envelope = JSON.parse(stored.envelope) as { data?: Record<string, unknown> };
    config = withEnvelopeLocale(config, envelope);
    prefill = stored.prefill ? (JSON.parse(stored.prefill) as Prefill) : undefined;
    if (standaloneDraftMismatch(envelope, definition)) {
      if (!context.isCurrent()) return;
      context.setLoaded({
        db, project: standaloneProject(projectId), config, definition, accessVersion: lockVersion,
        hasStartedSection: true, recall, accountName: account.name, standalone: true, projectId,
        siteId: STANDALONE_SITE_ID, binding: { projectId }, readOnlyData: envelope.data ?? {},
      });
      return;
    }
  }
  if (!row || needsSmartVaSnapshot) await setMeta(db, draftConfigKey(draftId), config);
  if (!context.isCurrent()) return;
  context.setLoaded({
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
    prefill,
    binding: { projectId, ...(prefill ? { prefill } : {}) },
  });
  context.setLocale(config.locale);
}

/**
 * A draft on a server project: a case's draft is first reconciled with the server's copy, then the host, the
 * saved or project config and the pinned or current form definition are resolved. Rejects on a store, network or
 * definition failure; the screen names it.
 */
export async function loadProjectDraft(context: FormLoadContext): Promise<void> {
  const { db, account, draftId, params, lockVersion, router } = context;
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
  context.setTrainingDraft(scopeFor(trainingProjectFor(account.user_id), existingDraft?.project_id ?? hostProjectId));
  if (!hostProjectId) {
    context.block(t("referenceDataUnavailable"));
    return;
  }
  if (params.deathId) {
    try {
      caseDetail = await fetchCaseDetail(account.user_id, db, params.deathId, {
        expectedProjectId: hostProjectId,
      });
      if (!context.isCurrent()) return;
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
    if (!context.isCurrent()) return;
  }
  let host = await resolveDraftHost(db, draftId, {
    ...params,
    projectId: hostProjectId,
  });
  if (!context.isCurrent()) return;
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
    context.block(t("referenceDataUnavailable"));
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
    context.block(t("referenceDataUnavailable"));
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
    context.block(t("referenceDataUnavailable"));
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
    envelope = await readServerBasedEnvelope(db, draftId);
    config = withEnvelopeLocale(config, envelope);
  } else if (existingDraft) {
    envelope = await readLocalEnvelope(db, draftId);
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
  if (!context.isCurrent()) return;
  const request = (path: string, requestOptions: { ifNoneMatch?: string }) =>
    authedRawRequest(account.user_id, path, {
      ifNoneMatch: requestOptions.ifNoneMatch,
      acceptGzip: true,
      projectId: hostProjectId,
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
        interviewLanguages: options.narration_languages ?? [],
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
        interviewLanguages: options.narration_languages ?? [],
        bundledOriginal: {
          instrument: bundledInstrument,
          instrumentVersion: bundledInstrument.version,
          extensions: config.enabledExtensions,
        },
        canUseBundledFallback: () =>
          canUseBundledFallbackForProject(account.user_id, db, hostProjectId),
        onServedDefinition: () =>
          markProjectDefinitionServed(account.user_id, db, hostProjectId),
      });
  if (!context.isCurrent()) return;
  if (!hasSavedConfig || needsSmartVaSnapshot || importedDraft || draftConflict || serverEnvelopeChanged || hasServerBase) {
    await setMeta(db, draftConfigKey(draftId), config);
  }
  if (!context.isCurrent()) return;
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
  const profileAnswers = profileInterviewerAnswers(await getOfflineProfile().catch(() => null));
  if (!context.isCurrent()) return;
  const hasStartedSection = Boolean(existingDraft && (!envelope || envelope.currentSection));
  context.setLoaded({
    db,
    project: project!,
    config,
    definition,
    accessVersion: lockVersion,
    hasStartedSection,
    recall,
    profileAnswers,
    accountName: referenceData?.bootstrap.user?.name,
    ...host,
  });
  context.setLocale(config.locale);
}
