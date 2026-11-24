/**
 * A supervisor's correction of a death report on the phone (docs/policy/mobile-sign-in.md, "Interview supervisors
 * on the phone"). Online only: the case is read with GET /intake/cases/<id> and the changed fields are sent at once
 * with PATCH /intake/deaths/<id>; nothing is queued or kept on the phone. The screen offers what the browser edit
 * does: the deceased, place and GPS fix, ABHA and registration numbers, the informant (behind the project's consent
 * decision) and notes, built from the interviewer form's parts (register.tsx). Case values, the consent decision,
 * the fix and the numbers live in React state only. The account database is read for the project's non-personal
 * settings (registration-number types, consent config) and filled by a live fetch where it has none (a
 * supervisor-only phone); no case value is ever written to it.
 */
import { FormThemeContext } from "@drguptavivek/who-2022-va";
import { randomUUID } from "expo-crypto";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { localToday, SEX_VALUES, validateRegistration, type RegistrationFields } from "../cases";
import { getNativeRegistrationCase, patchSupervisedDeath, type RegistrationCase, type RegistrationChanges } from "../deathRegistrationApi";
import { ApiError } from "../api";
import type { ConsentRecordEnvelope, ProjectConsentConfig } from "../consent";
import {
  coveredFieldsOf, getConsentConfig, refreshConsentConfig, registrationConsentGate, storedConsent, type StoredConsent,
} from "../consentStore";
import { IdentifierFields, identifierIssueText } from "../IdentifierFields";
import {
  identifierChanges, identifierFieldErrors, identifierIssues, identifierWarnings, isBadgeOnly, type CaseIdentifier, type IdentifierType,
} from "../identifiers";
import { openInterviewerDb } from "../interviewerDb";
import { NativeLocationCapture } from "../NativeLocationCapture";
import { PhoneNumbers } from "../PhoneInput";
import { getCachedIdentifierTypes, refreshIdentifierTypes } from "../sync";
import type { GpsFix } from "../web/LocationCapture";
import { RespondentConsentPanel } from "../web/StationConsentPanel";
import { t, uiLocale, type StringKey, type ThemeStringKey } from "../i18n";
import { registrationAgeInfoIssue } from "../registrationRules";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { spacing } from "../theme";
import { Button, Card, errorText, FieldHint, FieldLabel, Notice, Row, Screen, useUiStyles } from "../ui";
import { useWhoFormTheme } from "../whoWebTheme";
import {
  birthModeFor, ChoiceList, DECEASED_FIELDS, fixFrom, IDENTIFIER_FIELDS, NativeRegistrationFieldControl, NOTE_FIELDS, PLACE_FIELDS,
  REGISTRATION_FIELDS, registrationFieldsFromCase, sameFix, SEX_LABELS, TEXT_FIELDS,
  type BirthMode, type Field,
} from "./register";

/** `by` param value that puts /register in supervisor mode. */
export const SUPERVISOR_EDIT = "supervisor";
/** PATCH refusals the supervisor can act on (app/routes/api/intake.py). */
const DEATH_STALE = "death_stale";
const NOT_EDITABLE = ["case_completed", "details_pending"];
const CASE_CLOSED = "case_closed";

const BIRTH_LABELS: Record<BirthMode, StringKey> = { exact: "dobExact", "month-year": "dobMonthYear", year: "dobYear", unknown: "dobUnknown" };

type Loaded = { fields: RegistrationFields; updatedAt: string; location: GpsFix | null };

/** The case, the typed values, validation, and the one online save. `onSaved` runs after a successful PATCH. */
function useSupervisorDeathEdit(userId: string | undefined, deathId: string | undefined, onSaved: () => void) {
  const [base, setBase] = useState<Loaded>();
  const [projectId, setProjectId] = useState<string>();
  const [fields, setFields] = useState<RegistrationFields>();
  const [location, setLocation] = useState<GpsFix | null>(null);
  const [birthMode, setBirthMode] = useState<BirthMode>("exact");
  const [errors, setErrors] = useState<Partial<Record<Field, StringKey>>>({});
  const [message, setMessage] = useState("");
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  // Registration numbers: the project's types, whether this case lets the viewer change them, the server's
  // refusals and duplicate warnings per code.
  const [idTypes, setIdTypes] = useState<IdentifierType[]>([]);
  const [idEditable, setIdEditable] = useState(true);
  const [idErrors, setIdErrors] = useState<Record<string, string>>({});
  const [idWarnings, setIdWarnings] = useState<Record<string, string>>({});
  const [consentConfig, setConsentConfig] = useState<ProjectConsentConfig>();
  const [consent, setConsent] = useState<StoredConsent>();
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const applyCase = useCallback((loaded: RegistrationCase) => {
    const loadedFields = registrationFieldsFromCase(loaded);
    const fix = fixFrom(loaded);
    const source = loaded as unknown as { identifiers?: CaseIdentifier[]; can_edit_identifiers?: boolean };
    setBase({ fields: loadedFields, updatedAt: loaded.updated_at, location: fix });
    setProjectId(loaded.project_id);
    setFields(loadedFields);
    setLocation(fix);
    setBirthMode(birthModeFor(loadedFields));
    setIdEditable(!isBadgeOnly(source.identifiers) || source.can_edit_identifiers === true);
    setErrors({});
    setIdErrors({});
  }, []);

  const load = useCallback(async () => {
    if (!userId || !deathId) return;
    const loaded = await getNativeRegistrationCase(userId, deathId);
    if (alive.current) applyCase(loaded);
  }, [userId, deathId, applyCase]);

  useEffect(() => {
    setBase(undefined);
    setFields(undefined);
    setMessage("");
    load().catch(() => { if (alive.current) setMessage(t("supervisionDeathLoadFailed")); });
  }, [load]);

  // The project's non-personal settings: the cached copy where the account has one, else a live fetch. Reading
  // or refreshing these is the only use of the account database; no case value goes into it.
  useEffect(() => {
    if (!userId || !projectId) return undefined;
    let active = true;
    void (async () => {
      try {
        const db = await openInterviewerDb(userId);
        const types = await getCachedIdentifierTypes(db, projectId);
        const config = await getConsentConfig(db, projectId);
        if (active) { setIdTypes(types); setConsentConfig(config); }
        if (!types.length) {
          const fresh = (await refreshIdentifierTypes(userId, db, projectId)) ?? [];
          if (active) setIdTypes(fresh);
        }
        if (!config) {
          const fresh = await refreshConsentConfig(userId, db, projectId);
          if (active) setConsentConfig(fresh);
        }
      } catch { /* no settings: numbers stay hidden and the server enforces consent */ }
    })();
    return () => { active = false; };
  }, [userId, projectId]);

  const set = (name: Field) => (value: string) => setFields((current) => current && ({ ...current, [name]: value }));
  const setIssue = (name: Field, issue?: StringKey) => setErrors((current) => current[name] === issue ? current : { ...current, [name]: issue });
  const setIdentifier = (code: string, value: string) => {
    setFields((current) => current && ({ ...current, identifiers: { ...current.identifiers, [code]: value } }));
    setIdErrors((current) => (current[code] ? { ...current, [code]: "" } : current));
  };
  function chooseBirthMode(next: BirthMode) {
    setBirthMode(next);
    setFields((current) => current && ({
      ...current,
      date_of_birth: next === "exact" && birthMode === "exact" ? current.date_of_birth : undefined,
      date_of_birth_partial: next === birthMode ? current.date_of_birth_partial : undefined,
      age_years: next === "exact" ? undefined : current.age_years,
    }));
    setErrors((current) => ({ ...current, date_of_birth: undefined, date_of_birth_partial: undefined, age_years: undefined }));
  }

  // Informant details: where the project requires consent, one that is newly filled needs a granted decision,
  // recorded here and sent once with the change (as the interviewer's correction does).
  const covered = coveredFieldsOf(consentConfig);
  const valueOf = (source: RegistrationFields | undefined, name: string) => ((source as unknown as Record<string, string | undefined> | undefined)?.[name] ?? "");
  const informantEntered = covered.some((name) => valueOf(fields, name).trim() !== "" && valueOf(fields, name) !== valueOf(base?.fields, name));
  const needsConsent = informantEntered && consent?.envelope.decision !== "granted" && consentConfig?.consent_required === true;
  const phoneUnchanged = (name: "informant_phone" | "informant_phone_2") => (fields?.[name] ?? "") === (base?.fields[name] ?? "");
  const idShown = idTypes.length > 0 && idEditable;

  function recordConsent(envelope: ConsentRecordEnvelope) {
    if (!userId || !consentConfig) return;
    if (envelope.decision === "refused") {
      // A refusal never saves the informant's details: the covered fields go back to what is stored.
      setFields((current) => current && base && ({
        ...current,
        ...Object.fromEntries(covered.filter((name) => name in base.fields).map((name) => [name, valueOf(base.fields, name)])),
      }));
      setMessage("");
      return;
    }
    setConsent(storedConsent(envelope, consentConfig, userId));
    setMessage("");
  }

  async function save() {
    if (!userId || !deathId || !base || !fields || locked) return;
    const found = validateRegistration(fields, localToday()) as Partial<Record<Field, StringKey>>;
    // A stored phone left untouched is not an error (it may predate today's rule).
    for (const key of ["informant_phone", "informant_phone_2"] as const) if (phoneUnchanged(key)) delete found[key];
    if (registrationAgeInfoIssue(fields, base.fields)) found[birthMode === "unknown" ? "age_years" : birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial"] = birthMode === "unknown" ? "errRequired" : "errBirthOrAge";
    setErrors(found);
    const idIssues = idShown ? identifierIssues(idTypes, fields.identifiers ?? {}, false) : {};
    setIdErrors(Object.fromEntries(idTypes.filter((type) => idIssues[type.code]).map((type) => [type.code, identifierIssueText(type, idIssues[type.code])])));
    if (Object.keys(found).length || Object.keys(idIssues).length) { setMessage(t("registerFixErrors")); return; }
    if (needsConsent) { setMessage(t("consentNeededBeforeSave")); return; }
    const changes: RegistrationChanges = {};
    for (const name of REGISTRATION_FIELDS) {
      if ((fields[name] ?? "") !== (base.fields[name] ?? "")) changes[name] = (fields[name] ?? "").trim();
    }
    const idChanges = idShown ? identifierChanges(base.fields.identifiers, fields.identifiers) : {};
    if (Object.keys(idChanges).length) changes.identifiers = idChanges;
    // Absent keeps the stored fix, null clears it, a fix replaces it.
    if (!sameFix(location, base.location)) {
      changes.latitude = location?.latitude ?? null;
      changes.longitude = location?.longitude ?? null;
      changes.accuracy_m = location?.accuracy_m ?? null;
    }
    if (!Object.keys(changes).length) { onSaved(); return; }
    if (consent && covered.some((name) => name in changes)) changes.consent = consent.envelope;
    setBusy(true);
    setMessage("");
    try {
      const reply = await patchSupervisedDeath(userId, deathId, changes, base.updatedAt);
      // The decision went with this change; a later change asks again or relies on the one now on file.
      if (alive.current) setConsent(undefined);
      const duplicates = identifierWarnings(reply);
      if (Object.keys(duplicates).length) {
        // Saved: stay on the warning (Continue leaves, Edit keeps editing against what is now stored). The reply
        // may be the trimmed supervisor row, so the full case is read again.
        try { await load(); } catch { if (alive.current) setMessage(t("supervisionDeathLoadFailed")); }
        if (alive.current) setIdWarnings(duplicates);
        return;
      }
      onSaved();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.code === DEATH_STALE) {
        try { await load(); setMessage(t("supervisionDeathChanged")); } catch { setMessage(t("supervisionDeathLoadFailed")); }
      } else if (error instanceof ApiError && error.status === 409 && NOT_EDITABLE.includes(error.code ?? "")) {
        setLocked(true);
        setMessage(t("supervisionDeathNotEditable"));
      } else if (error instanceof ApiError && error.status === 409 && error.code === CASE_CLOSED) {
        setMessage(t("idCaseClosed"));
      } else if (error instanceof ApiError && error.status === 403) {
        setMessage(t("serverForbidden"));
      } else {
        const refused = identifierFieldErrors(error);
        if (Object.keys(refused).length) setIdErrors(refused);
        if (error instanceof ApiError && error.status === 422 && error.code?.startsWith("consent_")) {
          // The decision was unusable (or missing): ask again.
          setConsent(undefined);
          setMessage(t("consentNeededBeforeSave"));
        } else {
          setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : errorText(error));
        }
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  return {
    fields, location, setLocation, birthMode, errors, message, locked, busy, idTypes, idShown, idErrors, idWarnings, setIdWarnings,
    consent, setConsent, consentConfig, covered, needsConsent, phoneUnchanged, set, setIssue, setIdentifier, chooseBirthMode, recordConsent, save,
  };
}

export default function SupervisorDeathEdit() {
  const router = useRouter();
  const styles = useUiStyles();
  const whoTheme = useWhoFormTheme();
  const { userId, deathId } = useLocalSearchParams<{ userId?: string; deathId?: string }>();
  const edit = useSupervisorDeathEdit(userId, deathId, () => router.back());
  const { fields, errors } = edit;

  const field = (name: Field) => {
    const spec = TEXT_FIELDS.find((item) => item.name === name)!;
    if (name === "informant_phone") {
      return (
        <PhoneNumbers
          key={name}
          values={{ informant_phone: fields?.informant_phone ?? "", informant_phone_2: fields?.informant_phone_2 ?? "" }}
          errors={{
            informant_phone: errors.informant_phone ? t(errors.informant_phone) : undefined,
            informant_phone_2: errors.informant_phone_2 ? t(errors.informant_phone_2) : undefined,
          }}
          disabled={edit.locked}
          edge
          onChange={(phone, digits) => { edit.set(phone)(digits); edit.setIssue(phone); }}
          onValidity={(phone, valid) => edit.setIssue(phone, valid || edit.phoneUnchanged(phone) ? undefined : "errPhone")}
        />
      );
    }
    return (
      <View key={name} style={{ gap: 4 }}>
        <FieldLabel label={t(spec.label)} required={spec.required && !errors[name]} />
        <NativeRegistrationFieldControl
          field={name}
          label={t(spec.label)}
          value={fields?.[name] ?? ""}
          disabled={edit.locked}
          onChange={edit.set(name)}
          issue={errors[name]}
          onIssue={(issue) => edit.setIssue(name, issue)}
          appearance={name === "remarks" || name === "address" ? "multiline" : name === "abha_number" ? "numbers" : "exact"}
        />
        {spec.help ? <FieldHint>{t(spec.help)}</FieldHint> : null}
        {errors[name] ? <Text style={styles.error} accessibilityRole="alert">{t(errors[name]!)}</Text> : null}
      </View>
    );
  };

  if (!fields) {
    return (
      <Screen title={t("supervisionEditDeath")}>
        {edit.message ? <Notice tone="error">{edit.message}</Notice> : <Text style={styles.muted}>{t("loading")}</Text>}
      </Screen>
    );
  }
  const mode = edit.birthMode;
  const age = calculateRegistrationAge(fields);
  // As the interviewer form: the fields the consent notice covers are drawn in the Informant card.
  const informantNames = new Set<string>(edit.covered);
  const groupFields = (names: Field[]) => names.filter((name) => !informantNames.has(name));
  const informantFields = TEXT_FIELDS.slice(2).filter((spec) => informantNames.has(spec.name)).map((spec) => spec.name);
  const grouped = [...DECEASED_FIELDS, ...PLACE_FIELDS, ...IDENTIFIER_FIELDS, ...NOTE_FIELDS];
  const openInformantFields = TEXT_FIELDS.slice(2).filter((spec) => !informantNames.has(spec.name) && !grouped.includes(spec.name)).map((spec) => spec.name);
  const identifierFields = groupFields(IDENTIFIER_FIELDS);
  const noteFields = groupFields(NOTE_FIELDS);
  const consentGate = registrationConsentGate(edit.consentConfig);
  const consentNode = edit.consent ? (
    <Notice
      tone="info"
      action={!edit.locked ? <Row><Button size="sm" kind="secondary" label={t("consentChange")} disabled={edit.busy} onPress={() => edit.setConsent(undefined)} /></Row> : undefined}
    >
      <Text style={styles.text} testID="respondent-consent-recorded">{t(edit.consent.envelope.decision === "granted" ? "consentRecordedGranted" : "consentRecordedRefused")}</Text>
    </Notice>
  ) : consentGate.state === "ask" && !edit.locked && edit.needsConsent ? (
    <RespondentConsentPanel
      config={consentGate.config}
      language={uiLocale()}
      clientDraftId={null}
      busy={edit.busy}
      makeId={randomUUID}
      onDecision={edit.recordConsent}
    />
  ) : consentGate.state === "unavailable" && edit.needsConsent ? <FieldHint testID="informant-no-notice">{t("consentInformantNoNotice")}</FieldHint> : null;
  const informantShown = [...openInformantFields, ...informantFields];
  return (
    <Screen
      title={t("supervisionEditDeath")}
      footer={edit.locked ? undefined : (
        <Row>
          <Button label={t("save")} loading={edit.busy} disabled={edit.busy} onPress={() => void edit.save()} style={{ flex: 1 }} />
        </Row>
      )}
    >
      <FormThemeContext.Provider value={whoTheme}>
        <View style={{ gap: spacing.md }}>
          <Card label={t("registerSectionDeceased")} testID="supervisor-deceased">
            {field("deceased_name")}
            <View style={{ gap: spacing.xs }}>
              <FieldLabel label={t("fieldSex")} required={!errors.deceased_sex} />
              <ChoiceList
                accessibilityLabel={t("fieldSex")}
                options={SEX_VALUES.map((sex) => ({ value: sex, label: t(SEX_LABELS[sex]) }))}
                value={fields.deceased_sex as (typeof SEX_VALUES)[number] | undefined}
                disabled={edit.locked}
                onChange={(sex) => edit.set("deceased_sex")(sex)}
              />
              {errors.deceased_sex ? <Text style={styles.error} accessibilityRole="alert">{t(errors.deceased_sex)}</Text> : null}
            </View>
            {field("date_of_death")}
            <View style={{ gap: spacing.xs }}>
              <FieldLabel label={t("fieldDateOfBirth")} required={mode !== "unknown"} />
              <ChoiceList
                accessibilityLabel={`${t("fieldDateOfBirth")} ${t("dobPrecision")}`}
                options={(["exact", "month-year", "year", "unknown"] as const).map((value) => ({ value, label: t(BIRTH_LABELS[value]) }))}
                value={mode}
                disabled={edit.locked}
                onChange={edit.chooseBirthMode}
              />
              {mode === "exact" ? birthControl("date_of_birth", "dobExact") : null}
              {mode === "month-year" || mode === "year" ? birthControl("date_of_birth_partial", mode === "year" ? "dobYearField" : "dobMonthYear", mode) : null}
              {age ? <Text style={styles.muted}>{formatRegistrationAge(age)}</Text> : null}
            </View>
            {mode !== "exact" ? birthControl("age_years", mode === "unknown" ? "fieldEstimatedAgeRequired" : "fieldAge") : null}
            {groupFields(DECEASED_FIELDS).map(field)}
          </Card>
          <Card label={t("registerSectionPlace")} testID="supervisor-place">
            {groupFields(PLACE_FIELDS).map(field)}
            <View testID="supervisor-location">
              <NativeLocationCapture value={edit.location} disabled={edit.busy || edit.locked} onChange={edit.setLocation} />
            </View>
          </Card>
          {identifierFields.length || edit.idShown ? (
            <Card label={t("registerSectionIdentifiers")} testID="supervisor-identifiers">
              {identifierFields.map(field)}
              {edit.idShown ? (
                <IdentifierFields
                  title={false}
                  edge
                  types={edit.idTypes}
                  values={fields.identifiers ?? {}}
                  errors={edit.idErrors}
                  warnings={edit.idWarnings}
                  disabled={edit.locked}
                  onChange={edit.setIdentifier}
                  onContinue={() => router.back()}
                  onEdit={() => edit.setIdWarnings({})}
                />
              ) : null}
            </Card>
          ) : null}
          {consentNode || informantShown.length ? (
            <Card label={t("registerSectionInformant")} testID="supervisor-informant">
              {consentNode}
              {informantShown.map(field)}
            </Card>
          ) : null}
          {noteFields.length ? <Card label={t("registerSectionNotes")} testID="supervisor-notes">{noteFields.map(field)}</Card> : null}
          {edit.message ? <Notice tone="error">{edit.message}</Notice> : null}
        </View>
      </FormThemeContext.Provider>
    </Screen>
  );

  /** One birth-date or age control with its label and error line. */
  function birthControl(name: Field, label: StringKey | ThemeStringKey, appearance?: "month-year" | "year") {
    return (
      <View style={{ gap: 4 }}>
        <NativeRegistrationFieldControl
          field={name}
          label={t(label)}
          value={fields?.[name] ?? ""}
          disabled={edit.locked}
          onChange={edit.set(name)}
          issue={errors[name]}
          onIssue={(issue) => edit.setIssue(name, issue)}
          appearance={appearance}
        />
        {errors[name] ? <Text style={styles.error} accessibilityRole="alert">{t(errors[name]!)}</Text> : null}
      </View>
    );
  }
}
