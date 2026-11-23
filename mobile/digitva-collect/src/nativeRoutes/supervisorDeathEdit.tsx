/**
 * A supervisor's correction of a death report on the phone (docs/policy/mobile-sign-in.md, "Interview supervisors
 * on the phone"). Online only: the case is read with GET /intake/cases/<id> and the changed fields are sent at once
 * with PATCH /intake/deaths/<id>; nothing is queued or kept on the phone, and no interviewer database or reference
 * data is needed. Informant details, ABHA, location and registration numbers are not offered here.
 */
import { FormThemeContext } from "@drguptavivek/who-2022-va";
import { useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, View } from "react-native";

import { localToday, SEX_VALUES, validateRegistration, type RegistrationFields } from "../cases";
import { getNativeRegistrationCase, patchNativeDeathRegistration, type RegistrationChanges } from "../deathRegistrationApi";
import { ApiError } from "../api";
import { t, type StringKey, type ThemeStringKey } from "../i18n";
import { registrationAgeInfoIssue } from "../registrationRules";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { spacing } from "../theme";
import { Button, Card, errorText, FieldHint, FieldLabel, Notice, Row, Screen, useUiStyles } from "../ui";
import { useWhoFormTheme } from "../whoWebTheme";
import {
  birthModeFor, ChoiceList, NativeRegistrationFieldControl, registrationFieldsFromCase, SEX_LABELS, TEXT_FIELDS,
  type BirthMode, type Field,
} from "./register";

/** `by` param value that puts /register in supervisor mode. */
export const SUPERVISOR_EDIT = "supervisor";
/** PATCH refusals the supervisor can act on (app/routes/api/intake.py). */
const DEATH_STALE = "death_stale";
const NOT_EDITABLE = ["case_completed", "details_pending"];

/** The fields a supervisor edits here, by section, in the form's order. */
const DECEASED: Field[] = ["deceased_name", "date_of_death", "father_name", "mother_name"];
const PLACE: Field[] = ["place_of_death", "address", "address_house_street", "address_village_ward", "address_landmark"];
const NOTES: Field[] = ["remarks"];
const SHOWN = new Set<string>([...DECEASED, ...PLACE, ...NOTES, "deceased_sex", "date_of_birth", "date_of_birth_partial", "age_years"]);

const BIRTH_LABELS: Record<BirthMode, StringKey> = { exact: "dobExact", "month-year": "dobMonthYear", year: "dobYear", unknown: "dobUnknown" };

type Loaded = { fields: RegistrationFields; updatedAt: string };

/** The case, the typed values, validation, and the one online save. `onSaved` runs after a successful PATCH. */
function useSupervisorDeathEdit(userId: string | undefined, deathId: string | undefined, onSaved: () => void) {
  const [base, setBase] = useState<Loaded>();
  const [fields, setFields] = useState<RegistrationFields>();
  const [birthMode, setBirthMode] = useState<BirthMode>("exact");
  const [errors, setErrors] = useState<Partial<Record<Field, StringKey>>>({});
  const [message, setMessage] = useState("");
  const [locked, setLocked] = useState(false);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);
  useEffect(() => () => { alive.current = false; }, []);

  const load = useCallback(async () => {
    if (!userId || !deathId) return;
    const loaded = await getNativeRegistrationCase(userId, deathId);
    if (!alive.current) return;
    const loadedFields = registrationFieldsFromCase(loaded);
    setBase({ fields: loadedFields, updatedAt: loaded.updated_at });
    setFields(loadedFields);
    setBirthMode(birthModeFor(loadedFields));
    setErrors({});
  }, [userId, deathId]);

  useEffect(() => {
    setBase(undefined);
    setFields(undefined);
    setMessage("");
    load().catch(() => { if (alive.current) setMessage(t("supervisionDeathLoadFailed")); });
  }, [load]);

  const set = (name: Field) => (value: string) => setFields((current) => current && ({ ...current, [name]: value }));
  const setIssue = (name: Field, issue?: StringKey) => setErrors((current) => current[name] === issue ? current : { ...current, [name]: issue });
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

  async function save() {
    if (!userId || !deathId || !base || !fields || locked) return;
    // Only the fields this screen shows are checked: a stored value the screen cannot edit must not block the save.
    const found = Object.fromEntries(Object.entries(validateRegistration(fields, localToday())).filter(([name]) => SHOWN.has(name))) as Partial<Record<Field, StringKey>>;
    if (registrationAgeInfoIssue(fields, base.fields)) found[birthMode === "unknown" ? "age_years" : birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial"] = birthMode === "unknown" ? "errRequired" : "errBirthOrAge";
    setErrors(found);
    if (Object.keys(found).length) { setMessage(t("registerFixErrors")); return; }
    const changes: RegistrationChanges = {};
    for (const name of SHOWN) {
      const key = name as Field;
      if ((fields[key] ?? "") !== (base.fields[key] ?? "")) changes[key] = (fields[key] ?? "").trim();
    }
    if (!Object.keys(changes).length) { onSaved(); return; }
    setBusy(true);
    setMessage("");
    try {
      await patchNativeDeathRegistration(userId, deathId, changes, base.updatedAt);
      onSaved();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409 && error.code === DEATH_STALE) {
        try { await load(); setMessage(t("supervisionDeathChanged")); } catch { setMessage(t("supervisionDeathLoadFailed")); }
      } else if (error instanceof ApiError && error.status === 409 && NOT_EDITABLE.includes(error.code ?? "")) {
        setLocked(true);
        setMessage(t("supervisionDeathNotEditable"));
      } else {
        setMessage(error instanceof ApiError && error.status === 422 ? t("serverValidation") : errorText(error));
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }

  return { fields, birthMode, errors, message, locked, busy, set, setIssue, chooseBirthMode, save };
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
          appearance={name === "remarks" || name === "address" ? "multiline" : "exact"}
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
            {DECEASED.slice(2).map(field)}
          </Card>
          <Card label={t("registerSectionPlace")} testID="supervisor-place">{PLACE.map(field)}</Card>
          <Card label={t("registerSectionNotes")} testID="supervisor-notes">{NOTES.map(field)}</Card>
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
