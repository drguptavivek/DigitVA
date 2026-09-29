/**
 * The questionnaire for one draft, saved into the interviewer's own database.
 * Completing it marks the draft ready to send; the upload happens from the
 * worklist (push and purge).
 */
import {
  createWhoVa2022Instrument,
  type InstrumentDefinition,
  type SubmissionValidationResult
} from "@drguptavivek/who-2022-va";
import { WhoVaForm, type WhoVaDraftController } from "@drguptavivek/who-2022-va/native";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useEffect, useMemo, useRef, useState } from "react";
import { ActivityIndicator, AppState, Text, View } from "react-native";

import { useAppState } from "../src/AppState";
import { authedRequest } from "../src/auth";
import { createDraftStore, getDraftRow, getMeta, markCompleted, setMeta, type Db } from "../src/drafts";
import { t } from "../src/i18n";
import { openInterviewerDb } from "../src/interviewerDb";
import { platformServices } from "../src/platform";
import type { Bootstrap } from "../src/sync";
import { applyTranslations, type Translations } from "../src/translations";
import { Button, Row, Screen, styles } from "../src/ui";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

interface Loaded {
  db: Db;
  siteId: string;
  orgUnitId?: string;
  bootstrap: Bootstrap | undefined;
}

/**
 * The locale's translations: the copy cached in this interviewer's database,
 * else fetched once. Any failure falls back to English, as the web form does.
 */
async function translationsFor(userId: string, db: Db, code: string, locale: string): Promise<Translations | null> {
  if (locale === "en") return null;
  const key = `translations:${code}:${locale}`;
  const cached = await getMeta<Translations>(db, key);
  if (cached) return cached;
  try {
    const path = `/api/v1/instruments/${encodeURIComponent(code)}/translations/${encodeURIComponent(locale)}`;
    const { body } = await authedRequest<Translations>(userId, path);
    await setMeta(db, key, body);
    return body;
  } catch {
    return null;
  }
}

export default function Form() {
  const router = useRouter();
  const params = useLocalSearchParams<{ userId: string; draftId: string; siteId?: string; orgUnitId?: string }>();
  const { accounts } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const draftId = UUID.test(params.draftId ?? "") ? params.draftId : undefined;
  const [loaded, setLoaded] = useState<Loaded | undefined>();
  const [locale, setLocale] = useState("en");
  const [instrument, setInstrument] = useState<InstrumentDefinition | undefined>();
  const [message, setMessage] = useState("");
  const controller = useRef<WhoVaDraftController | undefined>(undefined);

  useEffect(() => {
    if (!account || !draftId) return;
    let active = true;
    void (async () => {
      const db = await openInterviewerDb(account.user_id);
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
    void translationsFor(account.user_id, loaded.db, code, locale).then((translations) => {
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

  const draftStore = useMemo(
    () => (loaded ? createDraftStore(loaded.db, { siteId: loaded.siteId, orgUnitId: loaded.orgUnitId }) : undefined),
    [loaded]
  );

  if (!account || !draftId) return <Redirect href="/" />;
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
    if (!result.valid || !loaded || !draftId) return;
    await controller.current?.saveDraft();
    await markCompleted(loaded.db, draftId);
    router.back();
  }

  const locales = loaded.bootstrap?.form_options?.available_locales ?? [];
  return (
    <Screen title={t("appName")} scroll={false}>
      <View style={{ paddingHorizontal: 16, gap: 8, paddingBottom: 8 }}>
        <Row>
          <Button kind="secondary" label={t("home")} onPress={() => void leave()} />
          <Button kind="secondary" label={t("save")} onPress={() => void controller.current?.saveDraft()} />
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
        onDraftError={() => setMessage(t("errGeneric"))}
        onDraftSaved={() => setMessage("")}
        onComplete={(result) => void complete(result)}
      />
      </View>
    </Screen>
  );
}
