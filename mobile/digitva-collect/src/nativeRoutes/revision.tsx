/** Edit one submitted interview in the encrypted revision queue. */
import {
  createWhoVa2022Instrument,
  WHO_VA_FORM_VERSION,
  type InstrumentDefinition,
  type SubmissionValidationResult,
} from "@drguptavivek/who-2022-va";
import {
  WhoVaForm,
  type WhoVaDraftController,
  type WhoVaSession,
} from "@drguptavivek/who-2022-va/native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, Alert, AppState, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { ApiError } from "../api";
import { authedRawRequest, SessionRevokedError, SignInRequiredError } from "../auth";
import type { Prefill } from "../cases";
import { getMeta, type Completion, type Db, type DeviceTimedDraft } from "../drafts";
import { createNativeDefinitionCache } from "../formDefinitionCache";
import {
  PinnedDefinitionError,
  resolveSavedEnvelopeDefinition,
  type ResolvedInstrument,
} from "../formDefinitionRuntime";
import { FormDefinitionError } from "../formDefinitions";
import {
  questionnaireDefault,
  t,
  UI_LOCALES,
} from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { initialDataFromPrefill } from "../prefill";
import {
  beginRevision,
  createRevisionDraftStore,
  discardRevision,
  effectiveRevisionOutcome,
  fetchSubmittedRevisions,
  getRevisionRow,
  queueRevision,
  reopenRevision,
  type RevisionReason,
  type RevisionRow,
} from "../revisions";
import {
  getCachedReferenceData,
  isUploadable,
  markProjectDefinitionServed,
  translationsFor,
  type ProjectSettings,
} from "../sync";
import { applyTranslations, type Translations } from "../translations";
import { Button, errorText, Row, Screen, useUiStyles } from "../ui";

const INCOMPLETE_OUTCOMES = new Set([
  "partially_completed",
  "respondent_unavailable",
  "refused",
]);
const REASONS: Array<{ code: RevisionReason; label: string; message: string }> = [
  {
    code: "interviewer_correction",
    label: "revisionReasonInterviewerCorrection",
    message: "revisionReasonMessageInterviewerCorrection",
  },
  {
    code: "respondent_correction",
    label: "revisionReasonRespondentCorrection",
    message: "revisionReasonMessageRespondentCorrection",
  },
  {
    code: "more_information",
    label: "revisionReasonMoreInformation",
    message: "revisionReasonMessageMoreInformation",
  },
  {
    code: "finish_partial",
    label: "revisionReasonFinishPartial",
    message: "revisionReasonMessageFinishPartial",
  },
];

interface RevisionConfig {
  projectId: string;
  locale: string;
  translationVersion?: number;
  enabledExtensions: string[];
  instrumentCode: string;
}

interface LoadedRevision {
  db: Db;
  row: RevisionRow;
  project: ProjectSettings;
  config: RevisionConfig;
  definition?: ResolvedInstrument;
  generation: number;
  accessVersion: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isIncompleteOutcome(value: unknown): boolean {
  return typeof value === "string" && INCOMPLETE_OUTCOMES.has(value);
}

function isPrefill(value: Record<string, unknown>): value is Record<string, unknown> & Prefill {
  return (
    (value.interviewer === undefined || isRecord(value.interviewer)) &&
    (value.deceased === undefined || isRecord(value.deceased)) &&
    (value.answers === undefined || isRecord(value.answers)) &&
    (value.lockedQuestionNames === undefined ||
      (Array.isArray(value.lockedQuestionNames) &&
        value.lockedQuestionNames.every((name) => typeof name === "string")))
  );
}

function attentionMessage(code: string | null): string {
  switch (code) {
    case "revision_locked":
      return t("revisionLocked");
    case "case_already_submitted":
      return t("revisionAlreadySubmitted");
    case "case_closed":
      return t("revisionCaseClosed");
    case "case_state_conflict":
      return t("revisionCaseConflict");
    case "invalid_reason":
    case "required_finish_partial":
      return t("revisionInvalidReason");
    case "outcome_regression":
      return t("revisionOutcomeRegression");
    case "not_found":
      return t("revisionUnavailable");
    case "answers_hash_invalid":
    case "local_hash_mismatch":
    case "invalid_revision_snapshot":
    case "invalid_revision_ack":
      return t("revisionRetry");
    default:
      return t("revisionRetry");
  }
}

function loadFailureMessage(error: unknown): string {
  if (error instanceof FormDefinitionError && error.code === "incompatible_engine") {
    return "Update the app to open this form. Your saved answers remain on this device.";
  }
  if (error instanceof PinnedDefinitionError && error.code === "unknown_saved_definition") {
    return "This interview's original form is unavailable. Your saved answers remain on this device.";
  }
  if (error instanceof Error && error.message === "revision_project_unavailable") {
    return t("revisionUnavailable");
  }
  if (error instanceof ApiError) {
    if (error.code === "revision_locked") return t("revisionLocked");
    if (error.code === "case_already_submitted") return t("revisionAlreadySubmitted");
    if (error.code === "case_closed") return t("revisionCaseClosed");
    if (error.code === "case_state_conflict") return t("revisionCaseConflict");
    if (error.status === 404) return t("revisionUnavailable");
  }
  if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
    return errorText(error);
  }
  return t("revisionRetry");
}

function configForRevision(row: RevisionRow, project: ProjectSettings): RevisionConfig {
  if (row.config?.projectId && row.config.projectId !== project.project_id) {
    throw new Error("revision_project_mismatch");
  }
  const options = project.form_options;
  const instrumentCode =
    row.config?.instrumentCode ??
    options?.form_types?.find((formType) => formType.is_default)?.instrument_code ??
    "WHO_2022_VA";
  const enabledExtensions = [
    ...(row.config?.enabledExtensions ?? options?.enabled_extensions ?? []),
  ];
  const savedLocale = row.envelope.locale || row.config?.locale;
  const locale = savedLocale ??
    questionnaireDefault(options?.available_locales, options?.default_locale);
  if (!UI_LOCALES.some((entry) => entry.code === locale)) {
    throw new Error("revision_locale_unavailable");
  }
  const translationVersion =
    row.envelope.translation_version ??
    row.config?.translationVersion ??
    options?.translation_versions?.[locale];
  return {
    projectId: project.project_id,
    locale,
    ...(translationVersion === undefined ? {} : { translationVersion }),
    enabledExtensions,
    instrumentCode,
  };
}

function normalizeEnvelope(
  envelope: DeviceTimedDraft,
  instrument: InstrumentDefinition,
): DeviceTimedDraft {
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

/** Resolve the saved definition pin; failures leave the encrypted revision unchanged. */
async function resolveRevisionInstrument(
  userId: string,
  db: Db,
  row: RevisionRow,
  project: ProjectSettings,
): Promise<ResolvedInstrument> {
  const options = project.form_options as ProjectSettings["form_options"] & {
    narration_languages?: Array<{ code: string; label: string }>;
  };
  const narrationLanguageCodes = (options.narration_languages ?? []).map(
    ({ code }) => code,
  );
  const savedExtensions = row.config?.enabledExtensions;
  const bundledExtensions = savedExtensions ?? [];
  const bundled = createWhoVa2022Instrument(bundledExtensions);
  const cache = createNativeDefinitionCache(
    db as Parameters<typeof createNativeDefinitionCache>[0],
    userId,
  );
  await cache.initialize();
  const request = (path: string, requestOptions: { ifNoneMatch?: string }) =>
    authedRawRequest(userId, path, {
      ifNoneMatch: requestOptions.ifNoneMatch,
      acceptGzip: true,
    });
  const resolved = await resolveSavedEnvelopeDefinition({
    accountId: userId,
    projectId: project.project_id,
    envelope: row.envelope,
    request,
    cache,
    narrationLanguageCodes,
    bundledLegacyDefinitions: [{
      instrument: bundled,
      instrumentVersion: bundled.version,
      extensions: bundledExtensions,
    }],
    legacyDefinitionExtensions: savedExtensions,
  });
  if (resolved.provenance === "served") {
    await markProjectDefinitionServed(userId, db, project.project_id);
  }
  return resolved;
}

export default function Revision() {
  const styles = useUiStyles();
  const router = useRouter();
  const params = useLocalSearchParams<{
    userId?: string;
    draftId?: string;
    projectId?: string;
    siteId?: string;
    vaSid?: string;
  }>();
  const { accounts, activity, onBeforeLock, chooseUiLocale, reload, lockVersion } = useAppState();
  const lockVersionRef = useRef(lockVersion);
  lockVersionRef.current = lockVersion;
  const account = accounts.find((candidate) => candidate.user_id === params.userId);
  const [loaded, setLoaded] = useState<LoadedRevision>();
  const [instrument, setInstrument] = useState<InstrumentDefinition>();
  const [reason, setReason] = useState<RevisionReason>();
  const [message, setMessage] = useState("");
  const [translationFallback, setTranslationFallback] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadAttempt, setLoadAttempt] = useState(0);
  const controller = useRef<WhoVaDraftController | undefined>(undefined);
  const session = useRef<WhoVaSession | undefined>(undefined);
  const generationRef = useRef(0);

  const isCurrentRevision = useCallback(
    (generation: number) =>
      generation === generationRef.current &&
      lockVersion === lockVersionRef.current &&
      Boolean(account && accounts.some((candidate) => candidate.user_id === account.user_id)) &&
      Boolean(account && isUnlocked(account.user_id)),
    [account, accounts, lockVersion],
  );

  useEffect(() => {
    const generation = ++generationRef.current;
    let active = true;
    setLoaded(undefined);
    setInstrument(undefined);
    setReason(undefined);
    setMessage("");
    controller.current = undefined;
    session.current = undefined;
    const draftId = params.draftId;
    const projectId = params.projectId;
    if (!account || !draftId || !projectId || !isUnlocked(account.user_id)) {
      return () => {
        active = false;
      };
    }

    void (async () => {
      try {
        const db = await openInterviewerDb(account.user_id);
        if (!active || !isCurrentRevision(generation)) return;
        const reference = await getCachedReferenceData(db);
        if (!active || !isCurrentRevision(generation)) return;
        const project = reference?.projects.find(
          ({ project: candidate }) => candidate.project_id === projectId,
        )?.project;
        if (!project) throw new Error("revision_project_unavailable");

        let row = await getRevisionRow(db, draftId);
        if (!row) {
          const summaries = await fetchSubmittedRevisions(account.user_id);
          if (!active || !isCurrentRevision(generation)) return;
          const summary = summaries.find((item) => item.draft_id === draftId);
          if (
            !summary ||
            summary.project_id !== projectId ||
            (params.siteId && summary.site_id !== params.siteId) ||
            (params.vaSid && summary.va_sid !== params.vaSid)
          ) {
            throw new Error("revision_project_unavailable");
          }
          row = await beginRevision(account.user_id, db, draftId);
        }
        if (!active || !isCurrentRevision(generation)) return;
        if (row.project_id !== projectId) throw new Error("revision_project_mismatch");
        if (row.state === "attention") {
          setLoaded({
            db,
            row,
            project,
            config: configForRevision(row, project),
            generation,
            accessVersion: lockVersion,
          });
          return;
        }
        if (row.state === "ready") {
          await reopenRevision(db, draftId);
          if (!active || !isCurrentRevision(generation)) return;
          row = (await getRevisionRow(db, draftId)) ?? row;
          if (!active || !isCurrentRevision(generation)) return;
        }
        if (!isPrefill(row.prefill)) throw new Error("revision_prefill_invalid");
        const config = configForRevision(row, project);
        const definition = await resolveRevisionInstrument(account.user_id, db, row, project);
        if (!active || !isCurrentRevision(generation)) return;
        const envelope = normalizeEnvelope(row.envelope, definition.instrument);
        const normalizedRow = { ...row, envelope };
        setLoaded({ db, row: normalizedRow, project, config, definition, generation, accessVersion: lockVersion });
      } catch (error) {
        if (!active || generation !== generationRef.current) return;
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
          await reload();
          if (active && isCurrentRevision(generation)) router.replace("/");
          return;
        }
        setMessage(loadFailureMessage(error));
      }
    })();
    return () => {
      active = false;
      generationRef.current += 1;
    };
  }, [account, isCurrentRevision, lockVersion, params.draftId, params.projectId, params.siteId, params.vaSid, reload, router, loadAttempt]);

  const baseInstrument = useMemo(
    () => loaded && loaded.row.state !== "attention" ? loaded.definition?.instrument : undefined,
    [loaded],
  );

  useEffect(() => {
    if (!loaded || !baseInstrument || !account) return;
    const generation = loaded.generation;
    let active = true;
    void (async () => {
      try {
        const pin = loaded.definition?.pin;
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
        const currentTranslationVersion = loaded.project.form_options.translation_versions?.[loaded.config.locale];
        let translations: Translations | null = null;
        if (isCurrentDefinition && loaded.config.translationVersion !== undefined) {
          const savedTranslations =
            loaded.config.translationVersion === currentTranslationVersion
              ? await translationsFor(
                  account.user_id,
                  loaded.db,
                  loaded.project.project_id,
                  loaded.config.instrumentCode,
                  loaded.config.locale,
                  loaded.config.translationVersion,
                )
              : await getMeta<Translations | null>(
                  loaded.db,
                  `translations:${loaded.config.instrumentCode}:${loaded.config.locale}:${loaded.config.translationVersion}`,
                  loaded.project.project_id,
                );
          translations = savedTranslations ?? null;
        }
        if (!active || !isCurrentRevision(generation)) return;
        await chooseUiLocale(loaded.config.locale);
        if (!active || !isCurrentRevision(generation)) return;
        setTranslationFallback(loaded.config.locale !== "en" && !translations);
        setInstrument(applyTranslations(baseInstrument, translations ?? null, loaded.config.locale));
        setMessage("");
      } catch (error) {
        if (!active || !isCurrentRevision(generation)) return;
        if (error instanceof SessionRevokedError || error instanceof SignInRequiredError) {
          await reload();
          if (active && isCurrentRevision(generation)) router.replace("/");
          return;
        }
        setMessage(t("revisionRetry"));
        setInstrument(undefined);
      }
    })();
    return () => {
      active = false;
    };
  }, [account, baseInstrument, chooseUiLocale, isCurrentRevision, loaded, reload, router]);

  const draftStore = useMemo(() => {
    if (!loaded || loaded.accessVersion !== lockVersion || !baseInstrument || loaded.row.state !== "editing") return undefined;
    const store = createRevisionDraftStore(
      loaded.db,
      loaded.row.draft_id,
      loaded.project.project_id,
    );
    return {
      ...store,
      load: async (id: string) => {
        if (!isCurrentRevision(loaded.generation)) return undefined;
        const draft = await store.load?.(id);
        if (!draft || !isCurrentRevision(loaded.generation)) return undefined;
        const normalized = normalizeEnvelope(draft as DeviceTimedDraft, baseInstrument);
        return normalized;
      },
      save: (draft: Parameters<typeof store.save>[0]) => {
        if (!isCurrentRevision(loaded.generation)) {
          return Promise.reject(new Error("revision_access_changed"));
        }
        activity();
        return store.save(draft);
      },
    };
  }, [activity, baseInstrument, isCurrentRevision, loaded, lockVersion]);

  const flush = useCallback(async () => {
    const current = loaded;
    if (!current || !isCurrentRevision(current.generation)) return;
    const draftController = controller.current;
    if (!draftController) throw new Error("revision_controller_unavailable");
    await draftController.saveDraft();
    if (!isCurrentRevision(current.generation)) return;
  }, [isCurrentRevision, loaded]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (next) => {
      if (next !== "active") {
        void flush().catch(() => {
          if (loaded && isCurrentRevision(loaded.generation)) setMessage(t("revisionUnsavedWarning"));
        });
      }
    });
    return () => subscription.remove();
  }, [flush, loaded?.generation]);

  useEffect(
    () => onBeforeLock(async () => {
      try {
        await flush();
      } catch {
        if (loaded && isCurrentRevision(loaded.generation)) setMessage(t("revisionUnsavedWarning"));
        throw new Error("revision_save_failed");
      }
    }),
    [flush, onBeforeLock],
  );

  if (loaded && loaded.accessVersion !== lockVersion) {
    return <ActivityIndicator style={{ flex: 1 }} />;
  }
  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  }
  if (!loaded) {
    return message ? (
      <Screen title={t("revisionTitle")}>
        <Text style={styles.error}>{message}</Text>
        <Button kind="secondary" label={t("home")} onPress={() => router.replace({ pathname: "/worklist", params: { userId: account.user_id } })} />
      </Screen>
    ) : <ActivityIndicator style={{ flex: 1 }} />;
  }
  if (loaded.row.state === "attention") {
    const current = loaded;
    const userId = account.user_id;
    const messageText = attentionMessage(current.row.refusal_code);
    const canEdit = [
      "invalid_reason",
      "required_finish_partial",
      "outcome_regression",
      "answers_hash_invalid",
      "local_hash_mismatch",
      "invalid_revision_snapshot",
      "invalid_revision_ack",
      "invalid_interview",
      "revision_locked",
    ].includes(current.row.refusal_code ?? "");
    async function editAttention() {
      if (busy || !isCurrentRevision(current.generation)) return;
      const generation = current.generation;
      setBusy(true);
      try {
        await reopenRevision(current.db, current.row.draft_id);
        if (!isCurrentRevision(generation)) return;
        const row = await getRevisionRow(current.db, current.row.draft_id);
        if (!isCurrentRevision(generation) || !row) return;
        if (!isPrefill(row.prefill)) throw new Error("revision_prefill_invalid");
        const config = configForRevision(row, current.project);
        const definition = await resolveRevisionInstrument(userId, current.db, row, current.project);
        if (!isCurrentRevision(generation)) return;
        const envelope = normalizeEnvelope(row.envelope, definition.instrument);
        setReason(undefined);
        setMessage("");
        setLoaded({ ...current, row: { ...row, envelope }, config, definition });
      } catch (error) {
        if (isCurrentRevision(generation)) setMessage(loadFailureMessage(error));
      } finally {
        if (isCurrentRevision(generation)) setBusy(false);
      }
    }
    return (
      <Screen title={t("revisionTitle")}>
        <Text style={styles.error}>{messageText}</Text>
        {message ? <Text style={styles.muted}>{message}</Text> : null}
        <Row>
          <Button kind="secondary" label={t("home")} onPress={() => router.replace({ pathname: "/worklist", params: { userId } })} />
          {canEdit ? (
            <Button kind="secondary" label={t("reviseInterview")} loading={busy} disabled={busy} onPress={() => void editAttention()} />
          ) : null}
          <Button kind="danger" label={t("discard")} onPress={() => Alert.alert(
            t("revisionTitle"),
            messageText,
            [
              { text: t("cancel"), style: "cancel" },
              { text: t("discard"), style: "destructive", onPress: () => void discardRevision(current.db, current.row.draft_id).then(() => { if (isCurrentRevision(current.generation)) router.replace({ pathname: "/worklist", params: { userId } }); }).catch(() => { if (isCurrentRevision(current.generation)) setMessage(t("revisionRetry")); }) },
            ],
          )} />
        </Row>
      </Screen>
    );
  }
  if (!draftStore || !instrument) {
    return (
      <Screen title={t("revisionTitle")}>
        <ActivityIndicator />
        {message ? <Text style={styles.error}>{message}</Text> : null}
        {message ? <Button kind="secondary" label={t("refresh")} onPress={() => setLoadAttempt((attempt) => attempt + 1)} /> : null}
        <Button kind="secondary" label={t("home")} onPress={() => router.replace({ pathname: "/worklist", params: { userId: account.user_id } })} />
      </Screen>
    );
  }

  const originalOutcome = loaded.row.original_outcome;
  const originalWasIncomplete = isIncompleteOutcome(originalOutcome);
  const originalNeedsFinishPartial =
    originalOutcome === null ||
    originalOutcome === "partially_completed" ||
    originalOutcome === "respondent_unavailable";
  const reasons = REASONS.filter(
    (item) => item.code !== "finish_partial" || originalNeedsFinishPartial,
  );
  const prefill = isPrefill(loaded.row.prefill) ? loaded.row.prefill : undefined;
  const initialData = initialDataFromPrefill(prefill);
  const current = loaded;
  const userId = account.user_id;
  async function complete(result: SubmissionValidationResult) {
    if (busy || !isCurrentRevision(current.generation)) return;
    if (!reason) {
      setMessage(t("revisionInvalidReason"));
      return;
    }
    const completion: Completion = { valid: result.valid, issues: result.issues };
    const nextOutcome = effectiveRevisionOutcome(result.data, completion);
    if (result.valid && nextOutcome === null) {
      setMessage(t("revisionConsentRequired"));
      return;
    }
    const nextIsIncomplete = isIncompleteOutcome(nextOutcome);
    if (!originalWasIncomplete && nextIsIncomplete) {
      setMessage(t("revisionOutcomeRegression"));
      return;
    }
    if (originalNeedsFinishPartial && nextOutcome === "completed" && reason !== "finish_partial") {
      setMessage(t("revisionInvalidReason"));
      return;
    }
    if (reason === "finish_partial" && (!originalNeedsFinishPartial || nextOutcome !== "completed")) {
      setMessage(t("revisionInvalidReason"));
      return;
    }
    if (!isUploadable(result.data, completion)) {
      setMessage(t("finishNeedsOutcome"));
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      // The controller save waits for the revision store's serialized write.
      await flush();
      if (!isCurrentRevision(current.generation)) return;
      const freshReference = await getCachedReferenceData(current.db);
      if (!isCurrentRevision(current.generation)) return;
      if (!freshReference?.projects.some(({ project }) => project.project_id === current.project.project_id)) {
        setMessage(t("revisionUnavailable"));
        return;
      }
      await queueRevision(current.db, current.row.draft_id, reason, completion);
      if (!isCurrentRevision(current.generation)) return;
      router.replace({ pathname: "/worklist", params: { userId } });
    } catch (error) {
      if (!isCurrentRevision(current.generation)) return;
      if (error instanceof Error && error.message === "consent_required") {
        setMessage(t("revisionConsentRequired"));
        return;
      }
      if (
        (error instanceof ApiError && error.code === "required_finish_partial") ||
        (error instanceof Error && error.message === "finish_partial_required")
      ) {
        setReason("finish_partial");
        setMessage(t("revisionInvalidReason"));
        return;
      }
      if (isCurrentRevision(current.generation)) setMessage(t("revisionRetry"));
    } finally {
      if (isCurrentRevision(current.generation)) setBusy(false);
    }
  }

  function finishIncomplete() {
    const result = session.current?.validate();
    if (result) void complete(result);
  }

  return (
    <Screen title={t("revisionTitle")} scroll={false}>
      <View style={{ paddingHorizontal: 16, gap: 8, paddingBottom: 8 }}>
        <Row>
          <Button kind="secondary" label={t("home")} disabled={busy} onPress={() => void flush().then(() => { if (isCurrentRevision(current.generation)) router.replace({ pathname: "/worklist", params: { userId } }); }).catch(() => { if (isCurrentRevision(current.generation)) setMessage(t("revisionUnsavedWarning")); })} />
          <Button kind="secondary" label={t("save")} disabled={busy} onPress={() => void flush().then(() => { if (isCurrentRevision(current.generation)) setMessage(t("revisionSaved")); }).catch(() => { if (isCurrentRevision(current.generation)) setMessage(t("revisionUnsavedWarning")); })} />
          <Button kind="secondary" label={t("finishIncomplete")} disabled={busy} onPress={finishIncomplete} />
        </Row>
        <Text style={styles.text}>{t("revisionReason")}</Text>
        <Row>
          {reasons.map((item) => (
            <Button
              key={item.code}
              kind={reason === item.code ? "primary" : "secondary"}
              label={t(item.label as never)}
              disabled={busy}
              onPress={() => {
                setReason(item.code);
                setMessage(t(item.message as never));
              }}
            />
          ))}
        </Row>
        {reason ? <Text style={styles.muted}>{t(REASONS.find((item) => item.code === reason)!.message as never)}</Text> : null}
        {translationFallback ? <Text style={styles.muted}>{t("questionnaireEnglishFallback")}</Text> : null}
        {message ? <Text style={styles.error}>{message}</Text> : null}
      </View>
      <View style={{ flex: 1 }}>
        <WhoVaForm
          key={`${loaded.row.draft_id}-${loaded.config.locale}`}
          instrument={instrument}
          locale={loaded.config.locale}
          showEnglish={loaded.config.locale !== "en"}
          draftId={loaded.row.draft_id}
          draftStore={draftStore}
          {...(initialData ? { initialData } : {})}
          {...(prefill?.lockedQuestionNames
            ? { lockedQuestionNames: prefill.lockedQuestionNames }
            : {})}
          autoSaveDraftOnChange
          onDraftController={(next) => {
            if (isCurrentRevision(current.generation)) controller.current = next;
          }}
          onReady={(next) => {
            if (isCurrentRevision(current.generation)) session.current = next;
          }}
          onDraftError={() => { if (isCurrentRevision(current.generation)) setMessage(t("revisionUnsavedWarning")); }}
          onDraftSaved={() => { if (isCurrentRevision(current.generation)) setMessage(""); }}
          onComplete={(result) => void complete(result)}
        />
      </View>
    </Screen>
  );
}
