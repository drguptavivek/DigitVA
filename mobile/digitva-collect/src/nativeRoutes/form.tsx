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
import {
  createWhoVa2022Instrument,
  type InstrumentDefinition,
  type SubmissionValidationResult,
} from "@drguptavivek/who-2022-va";
import {
  WhoVaForm,
  type WhoVaDraftController,
  type WhoVaSession,
} from "@drguptavivek/who-2022-va/native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, AppState, Text, View } from "react-native";

import { useAppState } from "../AppState";
import {
  getCase,
  getRegistration,
  prefillFromRegistration,
  resolveDraftHost,
  type DraftHost,
  type Prefill,
} from "../cases";
import {
  createDraftStore,
  getDraftRow,
  getMeta,
  markCompleted,
  setMeta,
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
import { initialDataFromPrefill } from "../prefill";
import {
  getCachedReferenceData,
  canUseBundledFallbackForProject,
  draftSyncDefaults,
  fetchCaseDetail,
  isUploadable,
  startsDirectly,
  targetsFrom,
  translationsFor,
  markProjectDefinitionServed,
  type ProjectSettings,
  type ReferenceData,
} from "../sync";
import { reconcileCaseDraft } from "../draftSync";
import { applyTranslations, type Translations } from "../translations";
import { Button, errorText, Row, Screen, useUiStyles } from "../ui";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Loaded extends DraftHost {
  db: Db;
  project: ProjectSettings;
  config: DraftConfig;
  definition: ResolvedInstrument;
  accessVersion: number;
}

interface DraftConfig {
  projectId: string;
  locale: string;
  enabledExtensions: string[];
  instrumentCode: string;
  translationVersion?: number;
}

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
      typeof config.translationVersion === "number")
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
  const { accounts, activity, onBeforeLock, chooseUiLocale, reload, lockVersion } =
    useAppState();
  const lockVersionRef = useRef(lockVersion);
  lockVersionRef.current = lockVersion;
  const account = accounts.find((a) => a.user_id === params.userId);
  const draftId = UUID.test(params.draftId ?? "") ? params.draftId : undefined;
  const [loaded, setLoaded] = useState<Loaded | undefined>();
  const [locale, setLocale] = useState("en");
  const [instrument, setInstrument] = useState<
    InstrumentDefinition | undefined
  >();
  const [translationFallback, setTranslationFallback] = useState(false);
  const [message, setMessage] = useState("");
  const [blockedReferenceData, setBlockedReferenceData] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const controller = useRef<WhoVaDraftController | undefined>(undefined);
  const session = useRef<WhoVaSession | undefined>(undefined);
  const loadGeneration = useRef(0);

  useEffect(() => {
    const generation = ++loadGeneration.current;
    let active = true;
    setLoaded(undefined);
    setInstrument(undefined);
    setBlockedReferenceData(false);
    setMessage("");
    setTranslationFallback(false);
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
        if (!hasSavedConfig || importedDraft || draftConflict || serverEnvelopeChanged || hasServerBase) {
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
        setLoaded({ db, project: project!, config, definition, accessVersion: lockVersion, ...host });
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

  useEffect(() => {
    if (!loaded || !baseInstrument || !account) return;
    let active = true;
    const code = loaded.config.instrumentCode;
    const version = loaded.config.translationVersion;
    void (async () => {
      try {
        const pin = loaded.definition.pin;
        const currentOptions = loaded.project.form_options;
        const currentExtensions = currentOptions.enabled_extensions;
        const isCurrentDefinition = Boolean(
          pin &&
          pin.instrumentVersion === currentOptions.instrument_version &&
          pin.definitionSha256 === currentOptions.definition_sha256 &&
          Array.isArray(currentExtensions) &&
          pin.definitionExtensions.length === currentExtensions.length &&
          [...currentExtensions].sort().every(
            (extension, index) => pin.definitionExtensions[index] === extension,
          ),
        );
        let translations: Translations | null = null;
        if (isCurrentDefinition && version !== undefined) {
          const savedTranslations =
            version === loaded.project.form_options.translation_versions?.[locale]
              ? await translationsFor(
                  account.user_id,
                  loaded.db,
                  loaded.project.project_id,
                  code,
                  locale,
                  version,
                )
              : await getMeta<Translations | null>(
                  loaded.db,
                  `translations:${code}:${locale}:${version}`,
                  loaded.project.project_id,
                );
          translations = savedTranslations ?? null;
        }
        if (!active) return;
        await chooseUiLocale(locale);
        setTranslationFallback(locale !== "en" && !translations);
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
    return {
      ...store,
      save: (draft: Parameters<typeof store.save>[0]) => {
        if (loaded.accessVersion !== lockVersionRef.current) {
          return Promise.reject(new Error("interview_access_changed"));
        }
        activity();
        return (async () => {
          // Keep the questionnaire choices with the encrypted draft so a later
          // pack refresh cannot silently change its language or modules.
          await setMeta(loaded.db, draftConfigKey(draftId), loaded.config);
          return store.save(draft);
        })();
      },
    };
  }, [loaded, draftId, activity, lockVersion]);

  // A stored draft replaces these on mount (the form's restore), so they only fill a new one.
  const initialData = useMemo(
    () => initialDataFromPrefill(loaded?.prefill),
    [loaded],
  );

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

  async function leave() {
    try {
      await controller.current?.saveDraft();
    } catch (error) {
      setMessage(errorText(error));
      return;
    }
    router.back();
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
              : current.project.form_options?.translation_versions?.[code],
        },
      };
    });
    setLocale(code);
  }

  async function complete(result: SubmissionValidationResult) {
    if (!loaded || !draftId) return;
    const completion = { valid: result.valid, issues: result.issues };
    if (!isUploadable(result.data, completion)) {
      setMessage(t("finishNeedsOutcome"));
      return;
    }
    await controller.current?.saveDraft();
    await markCompleted(loaded.db, draftId, completion);
    router.back();
  }

  /** Finish without the form's own "complete": allowed for an incomplete outcome only. */
  function finishIncomplete() {
    const result = session.current?.validate();
    if (result) void complete(result);
  }

  const locales = questionnaireLocales(
    loaded.project.form_options?.available_locales,
  );
  return (
    <Screen title={t("appName")} scroll={false}>
      <View style={{ paddingHorizontal: 16, gap: 8, paddingBottom: 8 }}>
        <Row>
          <Button
            kind="secondary"
            label={t("home")}
            onPress={() => void leave()}
          />
          <Button
            kind="secondary"
            label={t("save")}
            onPress={() => void controller.current?.saveDraft()}
          />
          <Button
            kind="secondary"
            label={t("finishIncomplete")}
            onPress={finishIncomplete}
          />
        </Row>
        {locales.length > 1 ? (
          <Row>
            <Text style={styles.muted}>{t("formLanguage")}</Text>
            {locales.map((entry) => (
              <Button
                key={entry.code}
                kind={entry.code === locale ? "primary" : "secondary"}
                label={entry.label}
                onPress={() => void switchLocale(entry.code)}
              />
            ))}
          </Row>
        ) : null}
        {translationFallback ? (
          <Text style={styles.muted}>{t("questionnaireEnglishFallback")}</Text>
        ) : null}
        {message ? <Text style={styles.error}>{message}</Text> : null}
      </View>
      <View style={{ flex: 1 }}>
        <WhoVaForm
          key={locale}
          instrument={instrument}
          locale={locale}
          showEnglish={locale !== "en"}
          draftId={draftId}
          draftStore={draftStore}
          {...(initialData ? { initialData } : {})}
          {...(loaded.prefill?.lockedQuestionNames
            ? { lockedQuestionNames: loaded.prefill.lockedQuestionNames }
            : {})}
          platform={platformServices}
          autoSaveDraftOnChange
          onDraftController={(next) => {
            if (loaded.accessVersion === lockVersionRef.current) {
              controller.current = next;
            }
          }}
          onReady={(next) => {
            if (loaded.accessVersion === lockVersionRef.current) {
              session.current = next;
            }
          }}
          onDraftError={() => setMessage(t("errGeneric"))}
          onDraftSaved={() => setMessage("")}
          onComplete={(result) => void complete(result)}
        />
      </View>
    </Screen>
  );
}
