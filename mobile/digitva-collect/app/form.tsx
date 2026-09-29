/**
 * The questionnaire for one draft, saved into the interviewer's own database.
 * Completing it marks the draft ready to send with the form engine's verdict
 * (`completion`); the upload happens from the worklist (push and purge). A
 * questionnaire the form reports invalid can be finished only when the
 * interviewer recorded the outcome as partially completed or respondent
 * unavailable, which the server accepts (web-intake.md, interview outcome).
 */
import {
  createWhoVa2022Instrument,
  type InstrumentDefinition,
  type SubmissionValidationResult
} from "@drguptavivek/who-2022-va";
import { WhoVaForm, type WhoVaDraftController, type WhoVaSession } from "@drguptavivek/who-2022-va/native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, AppState, Text, View } from "react-native";

import { useAppState } from "../src/AppState";
import { createDraftStore, getDraftRow, getMeta, markCompleted, type Db } from "../src/drafts";
import { t } from "../src/i18n";
import { isUnlocked, openInterviewerDb } from "../src/interviewerDb";
import { platformServices } from "../src/platform";
import { isUploadable, translationsFor, type Bootstrap } from "../src/sync";
import { applyTranslations } from "../src/translations";
import { Button, Row, Screen, styles } from "../src/ui";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Loaded {
  db: Db;
  siteId: string;
  orgUnitId?: string;
  bootstrap: Bootstrap | undefined;
}

export default function Form() {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId: string; draftId: string; siteId?: string; orgUnitId?: string }>();
  const { accounts, activity, onBeforeLock } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const draftId = UUID.test(params.draftId ?? "") ? params.draftId : undefined;
  const [loaded, setLoaded] = useState<Loaded | undefined>();
  const [locale, setLocale] = useState("en");
  const [instrument, setInstrument] = useState<InstrumentDefinition | undefined>();
  const [message, setMessage] = useState("");
  const controller = useRef<WhoVaDraftController | undefined>(undefined);
  const session = useRef<WhoVaSession | undefined>(undefined);

  useEffect(() => {
    if (!account || !draftId) return;
    let active = true;
    void (async () => {
      const db = await openInterviewerDb(account.user_id).catch(() => undefined);
      if (!db) return;
      const [row, bootstrap] = await Promise.all([getDraftRow(db, draftId), getMeta<Bootstrap>(db, "bootstrap")]);
      if (!active) return;
      if (row?.completed) {
        router.back();
        return;
      }
      const siteId = row?.site_id ?? params.siteId;
      if (!siteId) {
        router.back();
        return;
      }
      setLoaded({ db, siteId, orgUnitId: row?.org_unit_id ?? params.orgUnitId, bootstrap });
      setLocale(bootstrap?.form_options?.default_locale ?? "en");
    })();
    return () => {
      active = false;
    };
  }, [account, draftId, params.siteId, params.orgUnitId, router]);

  const baseInstrument = useMemo(
    () => (loaded ? createWhoVa2022Instrument(loaded.bootstrap?.form_options?.enabled_extensions ?? []) : undefined),
    [loaded]
  );

  useEffect(() => {
    if (!loaded || !baseInstrument || !account) return;
    let active = true;
    const code =
      loaded.bootstrap?.form_options?.form_types?.find((ft) => ft.is_default)?.instrument_code ?? "WHO_2022_VA";
    const version = loaded.bootstrap?.form_options?.translation_versions?.[locale];
    void translationsFor(account.user_id, loaded.db, code, locale, version).then((translations) => {
      if (active) setInstrument(applyTranslations(baseInstrument, translations, locale));
    });
    return () => {
      active = false;
    };
  }, [loaded, baseInstrument, locale, account]);

  // Save when the app leaves the foreground: Android may kill it there.
  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state !== "active") void controller.current?.saveDraft().catch(() => undefined);
    });
    return () => subscription.remove();
  }, []);

  // Locking saves the open draft before the database closes.
  useEffect(
    () => onBeforeLock(async () => void (await controller.current?.saveDraft())),
    [onBeforeLock]
  );

  // Autosaves count as activity, so typing a long answer never trips the idle lock.
  const draftStore = useMemo(() => {
    if (!loaded) return undefined;
    const store = createDraftStore(loaded.db, { siteId: loaded.siteId, orgUnitId: loaded.orgUnitId });
    return {
      ...store,
      save: (draft: Parameters<typeof store.save>[0]) => {
        activity();
        return store.save(draft);
      }
    };
  }, [loaded, activity]);

  if (!account || !draftId) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return <Redirect href={{ pathname: "/unlock", params: { userId: account.user_id } }} />;
  }
  if (!loaded || !instrument || !draftStore) return <ActivityIndicator style={{ flex: 1 }} />;

  async function leave() {
    try {
      await controller.current?.saveDraft();
    } catch {
      // The form reports save errors through onDraftError.
    }
    router.back();
  }

  async function switchLocale(code: string) {
    await controller.current?.saveDraft().catch(() => undefined);
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

  const locales = loaded.bootstrap?.form_options?.available_locales ?? [];
  return (
    <Screen title={t("appName")} scroll={false}>
      <View style={{ paddingHorizontal: 16, gap: 8, paddingBottom: 8 }}>
        <Row>
          <Button kind="secondary" label={t("home")} onPress={() => void leave()} />
          <Button kind="secondary" label={t("save")} onPress={() => void controller.current?.saveDraft()} />
          <Button kind="secondary" label={t("finishIncomplete")} onPress={finishIncomplete} />
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
        platform={platformServices}
        autoSaveDraftOnChange
        onDraftController={(next) => {
          controller.current = next;
        }}
        onReady={(next) => {
          session.current = next;
        }}
        onDraftError={() => setMessage(t("errGeneric"))}
        onDraftSaved={() => setMessage("")}
        onComplete={(result) => void complete(result)}
      />
      </View>
    </Screen>
  );
}
