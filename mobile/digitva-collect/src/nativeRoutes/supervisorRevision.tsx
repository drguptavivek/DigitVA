/**
 * A supervisor's correction of a submitted interview on the phone (docs/policy/mobile-sign-in.md, "Interview
 * supervisors on the phone"). Online only: the answers live in memory while this screen is open and are sent at once
 * (src/supervision/interviewRevision.ts); nothing is queued or written to the phone's database.
 */
import { type InstrumentDefinition, type SubmissionValidationResult } from "@drguptavivek/who-2022-va";
import { WhoVaForm, type WhoVaDraftController } from "@drguptavivek/who-2022-va/native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { ApiError } from "../api";
import { useAppState } from "../AppState";
import { ConfirmDialog } from "../ConfirmDialog";
import { FormTopBar, type SheetItem } from "../FormTopBar";
import { createRevisionSnapshot, revisionOutcome, type RevisionSnapshot } from "../client/revisions";
import { RevisionMemoryStore } from "../client/revisionMemoryStore";
import { goHome, RedirectHome } from "../goHome";
import { t } from "../i18n";
import { openInterviewerDb } from "../interviewerDb";
import { useLeaveGuard } from "../leaveGuard";
import { initialDataFromPrefill } from "../prefill";
import { attentionMessage, loadFailureMessage } from "../revisionMessages";
import { revisionName } from "../revisionLabel";
import { fetchProjectFormOptions, translationsForDraft, type ProjectSettings } from "../sync";
import { leavesScreen, loadSupervisorDraft, sendSupervisorRevision, sendFailureMessage } from "../supervision/interviewRevision";
import { applyTranslations } from "../translations";
import { useToast } from "../toast";
import { useStableAccount } from "../useStableAccount";
import { Button, Notice, Screen, useUiStyles } from "../ui";
import { useWhoFormTheme } from "../whoWebTheme";
import { configForRevision, isPrefill, normalizeEnvelope, resolveRevisionInstrument } from "./revision";

interface Loaded {
  store: RevisionMemoryStore;
  instrument: InstrumentDefinition;
  locale: string;
  name: string | null;
  initialJson: string;
}

export default function SupervisorRevision() {
  const styles = useUiStyles();
  const whoTheme = useWhoFormTheme();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const toast = useToast();
  const leaveGuard = useLeaveGuard();
  const { userId, draftId, vaSid, projectId, siteId } =
    useLocalSearchParams<{ userId?: string; draftId?: string; vaSid?: string; projectId?: string; siteId?: string }>();
  const { accounts, offline, chooseUiLocale, reload, holdRefresh } = useAppState();
  useEffect(() => holdRefresh?.(), [holdRefresh]);
  const account = useStableAccount(accounts.find((candidate) => candidate.user_id === userId));
  const [loaded, setLoaded] = useState<Loaded>();
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [busy, setBusy] = useState(false);
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [confirmFinish, setConfirmFinish] = useState(false);
  const [problemCount, setProblemCount] = useState(0);
  const controller = useRef<WhoVaDraftController | undefined>(undefined);
  const session = useRef<{ validate(): SubmissionValidationResult } | undefined>(undefined);
  // The frozen snapshot of the last send, kept so a retry after a network error sends the identical body.
  const pending = useRef<{ snapshot: RevisionSnapshot; dataJson: string } | undefined>(undefined);
  const accountId = account?.user_id;

  // Wait for the first connection, then never reload on a later connectivity change: that would drop unsent edits.
  const [wentOnline, setWentOnline] = useState(!offline);
  useEffect(() => { if (!offline) setWentOnline(true); }, [offline]);

  // The answers are re-read from the server on every open; offline there is nothing to read.
  useEffect(() => {
    if (!accountId || !draftId || !vaSid || !projectId || !siteId || !wentOnline) return undefined;
    let active = true;
    setLoaded(undefined);
    setError("");
    void (async () => {
      try {
        const row = await loadSupervisorDraft(accountId, { draft_id: draftId, va_sid: vaSid, project_id: projectId, site_id: siteId });
        if (row.refusal_code) { setError(attentionMessage(row.refusal_code)); return; }
        if (!isPrefill(row.prefill)) throw new Error("revision_prefill_invalid");
        // A supervisor-only phone caches no settings for a supervised project: read them live.
        const options = await fetchProjectFormOptions(accountId, projectId);
        const project = { project_id: projectId, project_name: "", web_intake_mode: String(options.web_intake_mode ?? ""), sites: [], form_options: options } as unknown as ProjectSettings; // no prefill policy: it is for new interviews
        const config = configForRevision(row, project);
        // The account database only holds the definition cache here; the answers never go into it.
        const db = await openInterviewerDb(accountId);
        const definition = await resolveRevisionInstrument(accountId, db, row, project);
        const envelope = normalizeEnvelope(row.envelope, definition.instrument);
        const translations = await translationsForDraft(
          accountId, db, projectId, config.instrumentCode, config.locale, config.translationVersion, options.translation_versions?.[config.locale],
        );
        if (!active) return;
        await chooseUiLocale(config.locale);
        const data = { ...initialDataFromPrefill(row.prefill), ...envelope.data };
        if (!active) return;
        setLoaded({
          store: new RevisionMemoryStore({ ...envelope, data } as ConstructorParameters<typeof RevisionMemoryStore>[0]),
          instrument: applyTranslations(definition.instrument, translations ?? null, config.locale),
          locale: config.locale,
          name: revisionName(row),
          initialJson: JSON.stringify(data),
        });
      } catch (failure) {
        if (!active) return;
        if (leavesScreen(failure)) {
          await reload();
          goHome(router);
          return;
        }
        setError(loadFailureMessage(failure));
      }
    })();
    return () => { active = false; };
  }, [accountId, draftId, vaSid, projectId, siteId, wentOnline, attempt, chooseUiLocale, reload, router]);

  // Leaving with edits that were never sent asks first; with none, Back just goes.
  const edited = () => Boolean(loaded && JSON.stringify(loaded.store.getCurrent()?.data) !== loaded.initialJson);
  leaveGuard.holds.current = edited;
  leaveGuard.handler.current = () => setConfirmLeave(true);

  async function complete(result: SubmissionValidationResult) {
    if (!loaded || !accountId || !projectId || !vaSid || busy) return;
    if (offline) { toast.show({ kind: "error", text: t("supervisionNeedsConnection") }); return; }
    setBusy(true);
    try {
      await controller.current?.saveDraft();
      const current = loaded.store.getCurrent();
      if (!current) throw new Error("revision_draft_missing");
      const dataJson = JSON.stringify(current.data);
      if (pending.current?.dataJson !== dataJson) {
        pending.current = undefined;
        if (!revisionOutcome(current.data, result.valid)) {
          toast.show({ kind: "error", text: result.valid ? t("revisionConsentRequired") : t("serverValidation") });
          return;
        }
        const snapshot = await createRevisionSnapshot({
          vaSid,
          reasonCode: "supervisor_correction",
          data: current.data,
          completion: { valid: result.valid, issues: result.issues },
          draft: {
            ...(current.startedAt ? { startedAt: current.startedAt } : {}),
            instrumentVersion: current.instrumentVersion,
            ...(current.definitionSha256 ? { definitionSha256: current.definitionSha256 } : {}),
            ...(current.definitionExtensions ? { definitionExtensions: current.definitionExtensions } : {}),
          },
          generation: 0,
        });
        pending.current = { snapshot, dataJson };
      }
      await sendSupervisorRevision(accountId, projectId, pending.current!.snapshot);
      pending.current = undefined;
      leaveGuard.release();
      router.back();
    } catch (failure) {
      if (leavesScreen(failure)) {
        await reload();
        goHome(router);
        return;
      }
      // The server decided (not found, changed, refused): the same body would fail again, so freeze a new one next time.
      if (failure instanceof ApiError) pending.current = undefined;
      toast.show({ kind: "error", text: sendFailureMessage(failure) });
    } finally {
      setBusy(false);
    }
  }

  if (!account) return <RedirectHome />;
  if (!loaded) {
    return (
      <Screen title={t("supervisionEditInterview")}>
        {offline ? <Notice tone="warning">{t("supervisionNeedsConnection")}</Notice> : null}
        {error ? <Text style={styles.error}>{error}</Text> : !offline ? <ActivityIndicator /> : null}
        {error ? <Button kind="secondary" label={t("refresh")} onPress={() => setAttempt((count) => count + 1)} /> : null}
        <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
      </Screen>
    );
  }
  return (
    <Screen title={t("supervisionEditInterview")} variant="immersive">
      <FormTopBar
        title={loaded.name ?? t("supervisionEditInterview")}
        {...(loaded.name ? { label: t("supervisionEditInterview") } : {})}
        saveState="saved"
        disabled={busy}
        onBack={() => router.back()}
        problemCount={problemCount}
        onProblems={() => controller.current?.showProblems()}
        menuItems={[
          { key: "finish", label: t("finishIncomplete"), onPress: () => setConfirmFinish(true) },
          { key: "preview", label: t("formPreviewAnswers"), onPress: () => controller.current?.openPreview() },
        ] satisfies SheetItem[]}
      />
      {confirmLeave ? (
        <ConfirmDialog
          title={t("supervisionEditLeaveTitle")}
          message={t("supervisionEditLeaveMessage")}
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
          onConfirm={() => { setConfirmFinish(false); const result = session.current?.validate(); if (result) void complete(result); }}
          onCancel={() => setConfirmFinish(false)}
        />
      ) : null}
      <View style={{ flex: 1, minHeight: 0 }}>
        <WhoVaForm
          theme={whoTheme}
          key={draftId}
          instrument={loaded.instrument}
          locale={loaded.locale}
          showEnglish={loaded.locale !== "en"}
          draftId={draftId!}
          draftStore={loaded.store}
          compactFooter
          safeInsets={{ top: insets.top, bottom: insets.bottom }}
          onProblemsChange={setProblemCount}
          autoSaveDraftOnChange
          onDraftController={(next) => { controller.current = next; }}
          onReady={(next) => { session.current = next; }}
          onComplete={(result) => void complete(result)}
        />
      </View>
    </Screen>
  );
}
