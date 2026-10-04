import {
  createWhoVa2022Instrument,
  type SubmissionData,
  type InstrumentDefinition,
  type SubmissionValidationResult
} from "@drguptavivek/who-2022-va";
import { WhoVaForm, type WhoVaDraftController } from "@drguptavivek/who-2022-va/web";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Platform, Pressable, StyleSheet, Text, View, type ViewStyle } from "react-native";

import { ClientApiError, getCaseDetail, getDraft, getInstrumentTranslations, getIntakeContext, getProjectFormOptions, startDraft, submitDraft, type DraftResponse, type FormOptions, type IntakeBootstrap } from "../client/api";
import { ServerDraftStore } from "../client/serverDraftStore";
import type { Prefill } from "../cases";
import { initialDataFromPrefill } from "../prefill";
import { useAppState } from "../AppState";
import { questionnaireDefault, questionnaireLocales, t } from "../i18n";
import { useTheme } from "../theme";
import { applyTranslations } from "../translations";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";

function instrumentCode(options: FormOptions): string {
  const code = options.form_types?.find((formType) => formType.is_default)?.instrument_code;
  if (code !== "WHO_2022_VA") throw new Error("unsupported_instrument");
  return code;
}

export default function InterviewScreen() {
  const router = useRouter();
  const params = useLocalSearchParams<{ draftId?: string; deathId?: string; projectId?: string; siteId?: string; orgUnitId?: string }>();
  const { bootstrap, chooseUiLocale } = useAppState();
  const styles = useUiStyles();
  const theme = useTheme();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [draftId, setDraftId] = useState(params.draftId);
  const [draft, setDraft] = useState<DraftResponse>();
  const [instrument, setInstrument] = useState<InstrumentDefinition>();
  const [locale, setLocale] = useState("en");
  const [locales, setLocales] = useState<FormOptions["available_locales"]>([]);
  const [store, setStore] = useState<ServerDraftStore>();
  const [controller, setController] = useState<WhoVaDraftController>();
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [translationFallback, setTranslationFallback] = useState(false);
  const [message, setMessage] = useState("");
  const draftPrefill = draft?.prefill as Prefill | undefined;

  const initialise = useCallback(async () => {
    if (!bootstrap) return;
    const nextIntake = await getIntakeContext(bootstrap.csrf);
    setIntake(nextIntake);
    let nextDraftId = draftId;
    if (!nextDraftId && params.deathId) {
      const { case: caseRow } = await getCaseDetail(bootstrap.links.intakeCases, params.deathId, bootstrap.csrf);
      if (!caseRow?.prefill) throw new Error("caseActionsUnavailable");
      if (!caseRow.project_id || !caseRow.site_id) throw new Error("case_context_missing");
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
      nextDraftId = started.draft.draft_id;
      setDraftId(nextDraftId);
    }
    if (!nextDraftId && !params.deathId && params.projectId && params.siteId) {
      const context = nextIntake.context.find((entry) => entry.project_id === params.projectId && entry.site_id === params.siteId);
      if (!context || !["direct", "both"].includes(context.web_intake_mode ?? "")) throw new Error("intake_configuration_unavailable");
      const started = await startDraft(
        bootstrap.links.intakeDrafts,
        {
          project_id: params.projectId,
          site_id: params.siteId,
          ...(params.orgUnitId ? { org_unit_id: params.orgUnitId } : {})
        },
        bootstrap.csrf
      );
      nextDraftId = started.draft.draft_id;
      setDraftId(nextDraftId);
    }
    if (!nextDraftId) throw new Error("draft_missing");
    const nextDraft = await getDraft(bootstrap.links.intakeDrafts, nextDraftId, bootstrap.csrf);
    const options = await getProjectFormOptions(nextDraft.draft.project_id, bootstrap.csrf);
    const base = createWhoVa2022Instrument(options.enabled_extensions ?? []);
    const savedLocale = nextDraft.envelope.locale;
    const nextLocale = savedLocale ?? questionnaireDefault(options.available_locales, options.default_locale);
    const translated = await translatedInstrument(base, nextLocale, options, bootstrap.csrf);
    const nextInstrument = translated.instrument;
    setTranslationFallback(translated.fallback);
    await chooseUiLocale(nextLocale);
    const sectionOf = new Map(base.questions.map((question) => [question.name, question.sectionPath.at(-1) ?? "_root"]));
    const prefill = nextDraft.prefill as Prefill;
    const initialData = initialDataFromPrefill(prefill) as SubmissionData;
    const nextStore = new ServerDraftStore({
      endpoint: bootstrap.links.intakeDrafts,
      csrf: bootstrap.csrf,
      sectionOf,
      initialData,
      identity: {
        instrumentId: nextInstrument.id,
        instrumentVersion: nextInstrument.version,
        firstSection: nextInstrument.sections[0]?.name ?? ""
      },
      locale: nextLocale,
      translationVersion: nextDraft.envelope.translation_version ?? options.translation_versions?.[nextLocale] ?? 0,
      onError: (error) => setMessage(browserErrorText(error))
    });
    await nextStore.load(nextDraftId);
    setDraft(nextDraft);
    setLocale(nextLocale);
    setLocales(questionnaireLocales(options.available_locales));
    setInstrument(nextInstrument);
    setStore(nextStore);
  }, [bootstrap, chooseUiLocale, draftId, params.deathId, params.orgUnitId, params.projectId, params.siteId]);

  useEffect(() => {
    void initialise().catch((error) => {
      if (error instanceof ClientApiError && [401, 403].includes(error.status)) {
        setInstrument(undefined);
        setStore(undefined);
      }
      setMessage(browserErrorText(error));
    });
  }, [initialise]);

  // Browsers do not reliably await asynchronous unload work. Warn while dirty
  // and attempt a flush; in-app navigation uses beforeNavigate and waits.
  useEffect(() => {
    if (typeof window === "undefined") return undefined;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
      void controller?.saveDraft().then(() => store?.flush()).catch(() => undefined);
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
    if (!bootstrap || !intake || !draft || !instrument || !store) return false;
    setBusy(true);
    setMessage("");
    const previousMetadata = store.getLocaleMetadata();
    try {
      if (nextLocale === locale) {
        await chooseUiLocale(nextLocale);
        return true;
      }
      await controller?.saveDraft();
      await store.flush();
      const options = await getProjectFormOptions(draft.draft.project_id, bootstrap.csrf);
      const next = await translatedInstrument(createWhoVa2022Instrument(options.enabled_extensions ?? []), nextLocale, options, bootstrap.csrf);
      store.setLocaleMetadata(nextLocale, options.translation_versions?.[nextLocale] ?? 0);
      // Persist the selected locale and the exact served translation before
      // remounting the form. The remount calls store.load(), so a metadata-only
      // change must already be on the server before the old form disappears.
      await controller?.saveDraft();
      await store.flush();
      await chooseUiLocale(nextLocale);
      setInstrument(next.instrument);
      setTranslationFallback(next.fallback);
      setLocale(nextLocale);
      return true;
    } catch (error) {
      store.restoreLocaleMetadata(previousMetadata);
      if (error instanceof ClientApiError && [401, 403].includes(error.status)) {
        setInstrument(undefined);
        setStore(undefined);
      }
      setMessage(browserErrorText(error));
      return false;
    } finally {
      setBusy(false);
    }
  }, [bootstrap, chooseUiLocale, controller, draft, instrument, intake, locale, store]);

  async function complete(result: SubmissionValidationResult) {
    if (!bootstrap || !draftId || !store) return;
    setBusy(true);
    setMessage("");
    try {
      await controller?.saveDraft();
      await store.flush();
      const submission = await submitDraft(bootstrap.links.intakeDrafts, draftId, { valid: result.valid, issues: result.issues }, bootstrap.csrf);
      router.replace(submission.superseded
        ? { pathname: "/collection", params: { superseded: "1" } }
        : "/collection");
    } catch (error) {
      setMessage(browserErrorText(error));
    } finally {
      setBusy(false);
    }
  }

  async function leave() {
    try {
      await controller?.saveDraft();
      await store?.flush();
      router.back();
    } catch (error) {
      setMessage(browserErrorText(error));
    }
  }

  const beforeNavigate = useCallback(async () => {
    try {
      await controller?.saveDraft();
      await store?.flush();
      return true;
    } catch (error) {
      setMessage(browserErrorText(error));
      return false;
    }
  }, [controller, store]);

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
      title={t("interviewTitle")}
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
      {instrument && store && draftId ? (
        <>
          <View style={styles.row}>
            <Button kind="secondary" label={t("backToCollection")} onPress={() => void leave()} />
            <Button loading={busy} kind="secondary" label={t("save")} onPress={() => void store.flush().catch((error) => setMessage(browserErrorText(error)))} />
          </View>
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
              onChange={() => setDirty(true)}
              onDraftSaved={() => setDirty(false)}
              onDraftError={(error) => setMessage(browserErrorText(error))}
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
