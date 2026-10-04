/**
 * Register a death offline: the web register form's fields, checked with the
 * same rules (src/cases.ts validateRegistration), saved as a pending
 * registration with its own client_death_id and sent on the next sync. With
 * `clientDeathId` it edits one the server refused (it becomes pending again,
 * same id). "Save and start interview" opens the questionnaire on it at once.
 */
import { randomUUID } from "expo-crypto";
import { Redirect, useLocalSearchParams, useRouter } from "expo-router";
import { useCallback, useEffect, useRef, useState } from "react";
import { Text, TextInput, View } from "react-native";
import { WhoVaQuestionControls } from "@drguptavivek/who-2022-va/native";
import {
  resolveUiMessages,
  WHO_VA_BUILT_IN_UI_TRANSLATIONS,
  type AnswerValue,
  type InstrumentQuestion,
  type QuestionControl,
  type ValidationIssue,
} from "@drguptavivek/who-2022-va";

import { useAppState } from "../AppState";
import {
  cleanRegistration,
  getRegistration,
  localToday,
  MAX_REGISTRATION_AGE,
  registrationNeedsAgeConfirmation,
  saveRegistration,
  SEX_VALUES,
  validateRegistration,
  type RegistrationFields,
} from "../cases";
import { type Db } from "../drafts";
import { t, uiLocale, type StringKey } from "../i18n";
import { isUnlocked, openInterviewerDb } from "../interviewerDb";
import { platformServices } from "../platform";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import {
  getCachedReferenceData,
  registersDeaths,
  targetsFrom,
  type ProjectSettings,
  type ReferenceData,
  type Target,
} from "../sync";
import { Button, Row, Screen, useUiStyles } from "../ui";

type Field = keyof RegistrationFields;
type BirthMode = "exact" | "month-year" | "year";

/** Text fields in the web form's order, with their label and keyboard. */
const TEXT_FIELDS: Array<{
  name: Field;
  label: StringKey;
  keyboard?: "numeric" | "phone-pad";
  help?: StringKey;
}> = [
  { name: "deceased_name", label: "fieldDeceasedName" },
  { name: "date_of_death", label: "fieldDateOfDeath" },
  { name: "address", label: "fieldAddress" },
  { name: "informant_name", label: "fieldInformantName" },
  {
    name: "informant_phone",
    label: "fieldInformantPhone",
    keyboard: "phone-pad",
    help: "phoneHelp",
  },
  { name: "abha_number", label: "fieldAbhaNumber" },
  { name: "abha_address", label: "fieldAbhaAddress" },
  { name: "place_of_death", label: "fieldPlaceOfDeath" },
  { name: "address_house_street", label: "fieldHouseStreet" },
  { name: "address_village_ward", label: "fieldVillageWard" },
  { name: "address_landmark", label: "fieldLandmark" },
  { name: "father_name", label: "fieldFatherName" },
  { name: "mother_name", label: "fieldMotherName" },
  {
    name: "informant_phone_2",
    label: "fieldInformantPhone2",
    keyboard: "phone-pad",
  },
  { name: "remarks", label: "fieldRemarks", help: "remarksHelp" },
];

function birthModeFor(fields: RegistrationFields): BirthMode {
  if (fields.date_of_birth?.trim()) return "exact";
  if (/^\d{4}-\d{2}$/.test(fields.date_of_birth_partial?.trim() ?? ""))
    return "month-year";
  if (/^\d{4}$/.test(fields.date_of_birth_partial?.trim() ?? "")) return "year";
  return "exact";
}

export function requiredBirthField(
  mode: BirthMode,
  fields: RegistrationFields,
): "date_of_birth" | "date_of_birth_partial" | undefined {
  if (mode === "exact")
    return fields.date_of_birth?.trim() ? undefined : "date_of_birth";
  return fields.date_of_birth_partial?.trim()
    ? undefined
    : "date_of_birth_partial";
}

function nativeQuestion(
  field: Field,
  label: string,
  appearance?: string,
): InstrumentQuestion {
  const control: QuestionControl =
    field === "date_of_death" ||
    field === "date_of_birth" ||
    field === "date_of_birth_partial"
      ? "date"
      : field === "age_years"
        ? "integer"
        : "text";
  return {
    name: field,
    order: 0,
    sourceRow: 0,
    sourceType: "digitva-registration",
    dataType:
      control === "date" ? "date" : control === "integer" ? "number" : "string",
    control,
    label: { en: label },
    hint: {},
    guidance: {},
    required: field === "deceased_name" || field === "date_of_death",
    readOnly: false,
    constraintMessage: {},
    sectionPath: [],
    ...(appearance ? { appearance } : {}),
  };
}

export function NativeRegistrationFieldControl({
  field,
  label,
  value,
  onChange,
  issue,
  onIssue,
  appearance = "exact",
}: {
  field: Field;
  label: string;
  value: string;
  onChange: (value: string) => void;
  issue?: StringKey;
  onIssue?: (issue?: StringKey) => void;
  appearance?: "exact" | "month-year" | "year" | "multiline";
}) {
  const question = nativeQuestion(
    field,
    label,
    appearance === "exact" ? undefined : appearance,
  );
  const issues: ValidationIssue[] = issue
    ? [{ question: field, code: "constraint", message: t(issue) }]
    : [];
  const locale = uiLocale();
  const onIssueRef = useRef(onIssue);
  onIssueRef.current = onIssue;
  const onDraftIssue = useCallback(
    (_question: string, draftIssue?: ValidationIssue) => {
      onIssueRef.current?.(draftIssue ? "errDate" : undefined);
    },
    [],
  );
  const controlProps = {
    question,
    value: (field === "age_years"
      ? value
        ? Number(value)
        : undefined
      : field === "date_of_birth_partial" && value
        ? `${value}${appearance === "year" ? "-01-01" : "-01"}`
        : value || undefined) as AnswerValue | undefined,
    data: {},
    locale,
    messages: resolveUiMessages(locale, WHO_VA_BUILT_IN_UI_TRANSLATIONS),
    issues,
    onAnswer: (next: AnswerValue | undefined) => {
      if (
        field === "age_years" &&
        typeof next === "number" &&
        (next < 0 || next > MAX_REGISTRATION_AGE)
      ) {
        onChange(String(next));
        onIssue?.("errAge");
        return;
      }
      if (field === "date_of_birth_partial" && typeof next === "string") {
        onChange(
          appearance === "month-year" ? next.slice(0, 7) : next.slice(0, 4),
        );
      } else onChange(next == null ? "" : String(next));
      onIssue?.();
    },
  };
  if (question.control === "date") {
    return (
      <WhoVaQuestionControls.Date
        {...controlProps}
        platform={platformServices}
        onDraftIssue={onDraftIssue}
      />
    );
  }
  if (question.control === "integer")
    return <WhoVaQuestionControls.Integer {...controlProps} />;
  return <WhoVaQuestionControls.Text {...controlProps} />;
}

const SEX_LABELS: Record<(typeof SEX_VALUES)[number], StringKey> = {
  male: "sexMale",
  female: "sexFemale",
  undetermined: "sexUndetermined",
  unknown: "sexUnknown",
};

export default function Register() {
  const styles = useUiStyles();
  const router = useRouter();
  const params = useLocalSearchParams<{
    userId: string;
    projectId?: string;
    clientDeathId?: string;
  }>();
  const { accounts } = useAppState();
  const account = accounts.find((a) => a.user_id === params.userId);
  const [db, setDb] = useState<Db | undefined>();
  const [targets, setTargets] = useState<Target[]>([]);
  const [referenceData, setReferenceData] = useState<ReferenceData>();
  const [projectId, setProjectId] = useState<string | undefined>(
    params.projectId,
  );
  const [target, setTarget] = useState<Target | undefined>();
  const [fields, setFields] = useState<RegistrationFields>({
    deceased_name: "",
    deceased_sex: "",
    date_of_death: "",
  });
  const [birthMode, setBirthMode] = useState<BirthMode>("exact");
  const [errors, setErrors] = useState<Partial<Record<Field, StringKey>>>({});
  const [message, setMessage] = useState("");
  const [ageConfirmationPending, setAgeConfirmationPending] = useState(false);
  const [ageConfirmationStartAfter, setAgeConfirmationStartAfter] =
    useState(false);
  const [busy, setBusy] = useState(false);
  const editing = params.clientDeathId;

  useEffect(() => {
    if (!account) return;
    let active = true;
    void (async () => {
      try {
        const handle = await openInterviewerDb(account.user_id);
        const [referenceData, existing] = await Promise.all([
          getCachedReferenceData(handle),
          editing
            ? getRegistration(handle, editing)
            : Promise.resolve(undefined),
        ]);
        if (!active) return;
        setDb(handle);
        setReferenceData(referenceData);
        const nextProjectId =
          existing?.project_id ??
          params.projectId ??
          (referenceData?.projects.length === 1
            ? referenceData.projects[0].project.project_id
            : undefined);
        setProjectId(nextProjectId);
        if (existing) {
          const selected = referenceData?.projects.find(
            ({ project }) => project.project_id === nextProjectId,
          );
          const choices = selected
            ? targetsFrom(selected.project, selected.units).filter((c) =>
                registersDeaths(selected.project, c.siteId),
              )
            : [];
          setTargets(choices);
          setFields(existing.fields);
          setBirthMode(birthModeFor(existing.fields));
          setTarget(
            choices.find(
              (c) =>
                c.siteId === existing.site_id &&
                (c.orgUnitId ?? null) === existing.org_unit_id,
            ) ?? {
              key: "existing",
              label: existing.site_id,
              siteId: existing.site_id,
              orgUnitId: existing.org_unit_id ?? undefined,
              projectId: existing.project_id,
            },
          );
        } else if (!referenceData) {
          setTargets([]);
          setMessage(t("referenceDataUnavailable"));
          return;
        } else {
          const selected = referenceData?.projects.find(
            ({ project }) => project.project_id === nextProjectId,
          );
          const choices = selected
            ? targetsFrom(selected.project, selected.units).filter((c) =>
                registersDeaths(selected.project, c.siteId),
              )
            : [];
          setTargets(choices);
          if (choices.length === 1) {
            setTarget(choices[0]);
          }
        }
      } catch {
        if (active) setMessage(t("registerLoadFailed"));
      }
    })();
    return () => {
      active = false;
    };
  }, [account, editing]);

  if (!account) return <Redirect href="/" />;
  if (!isUnlocked(account.user_id)) {
    return (
      <Redirect
        href={{ pathname: "/unlock", params: { userId: account.user_id } }}
      />
    );
  }

  const set = (name: Field) => (value: string) => {
    setFields((current) => ({ ...current, [name]: value }));
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
  };

  const setFieldIssue = (field: Field, issue?: StringKey) => {
    setErrors((current) =>
      current[field] === issue ? current : { ...current, [field]: issue },
    );
  };

  const chooseBirthMode = (next: BirthMode) => {
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
    setBirthMode(next);
    setFields((current) => ({
      ...current,
      date_of_birth:
        next === "exact" && birthMode === "exact"
          ? current.date_of_birth
          : undefined,
      date_of_birth_partial:
        next === birthMode ? current.date_of_birth_partial : undefined,
      age_years: next === "exact" ? undefined : current.age_years,
    }));
    setErrors((current) => ({
      ...current,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined,
    }));
  };

  const renderTextField = (field: (typeof TEXT_FIELDS)[number]) => (
    <View key={field.name} style={{ gap: 4 }}>
      <Text style={styles.muted}>{t(field.label)}</Text>
      {field.name === "informant_phone" ||
      field.name === "informant_phone_2" ? (
        <TextInput
          accessibilityLabel={t(field.label)}
          autoCorrect={false}
          inputMode="tel"
          keyboardType="phone-pad"
          style={styles.input}
          value={fields[field.name] ?? ""}
          onChangeText={(value) => {
            set(field.name)(value);
            setFieldIssue(field.name);
          }}
        />
      ) : (
        <NativeRegistrationFieldControl
          field={field.name}
          label={t(field.label)}
          value={fields[field.name] ?? ""}
          onChange={set(field.name)}
          issue={errors[field.name]}
          onIssue={(issue) => setFieldIssue(field.name, issue)}
          appearance={
            field.name === "remarks" || field.name === "address"
              ? "multiline"
              : "exact"
          }
        />
      )}
      {field.help ? <Text style={styles.muted}>{t(field.help)}</Text> : null}
      {errorFor(field.name)}
    </View>
  );

  async function save(startAfter: boolean, confirmAge = false) {
    if (!db || !account || !target || !projectId) return;
    setMessage("");
    const found = validateRegistration(fields, localToday());
    const selectedBirthField = requiredBirthField(birthMode, fields);
    const nextErrors = selectedBirthField
      ? { ...found, [selectedBirthField]: "errRequired" as const }
      : found;
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      setAgeConfirmationPending(false);
      setAgeConfirmationStartAfter(false);
      setMessage(t("registerFixErrors"));
      return;
    }
    if (!confirmAge && registrationNeedsAgeConfirmation(fields)) {
      setAgeConfirmationPending(true);
      setAgeConfirmationStartAfter(startAfter);
      return;
    }
    setAgeConfirmationPending(false);
    setAgeConfirmationStartAfter(false);
    const clientDeathId = editing ?? randomUUID();
    setBusy(true);
    try {
      await saveRegistration(db, {
        project_id: projectId,
        client_death_id: clientDeathId,
        site_id: target.siteId,
        org_unit_id: target.orgUnitId ?? null,
        fields: cleanRegistration(fields),
      });
      if (!startAfter) {
        router.back();
        return;
      }
      router.replace({
        pathname: "/form",
        params: {
          userId: account.user_id,
          projectId,
          siteId: target.siteId,
          ...(target.orgUnitId ? { orgUnitId: target.orgUnitId } : {}),
          draftId: randomUUID(),
          clientDeathId,
        },
      });
    } catch {
      setMessage(t("registerSaveFailed"));
    } finally {
      setBusy(false);
    }
  }

  const errorFor = (name: Field) =>
    errors[name] ? (
      <Text style={styles.error} accessibilityRole="alert">
        {t(errors[name]!)}
      </Text>
    ) : null;
  const chooseProject = (nextProjectId: string) => {
    const selected = referenceData?.projects.find(
      ({ project }) => project.project_id === nextProjectId,
    );
    setProjectId(nextProjectId);
    setTarget(undefined);
    setTargets(
      selected
        ? targetsFrom(selected.project, selected.units).filter((choice) =>
            registersDeaths(selected.project, choice.siteId),
          )
        : [],
    );
  };

  return (
    <Screen title={t("registerDeath")}>
      {referenceData && referenceData.projects.length > 1 ? (
        <View style={{ gap: 8 }}>
          <Text style={styles.text}>{t("chooseProject")}</Text>
          {referenceData.projects.map(({ project }) => (
            <Button
              key={project.project_id}
              kind={project.project_id === projectId ? "primary" : "secondary"}
              label={project.project_name}
              onPress={() => chooseProject(project.project_id)}
            />
          ))}
        </View>
      ) : null}
      <Text style={styles.text}>{t("chooseSite")}</Text>
      {targets.length === 0 && !target ? (
        <Text style={styles.muted}>{t("noSites")}</Text>
      ) : null}
      <View style={{ gap: 8 }}>
        {editing && target ? (
          <Text style={styles.muted}>{target.label}</Text>
        ) : (
          targets.map((choice) => (
            <Button
              key={choice.key}
              kind={choice.key === target?.key ? "primary" : "secondary"}
              label={choice.label}
              onPress={() => setTarget(choice)}
            />
          ))
        )}
      </View>
      {renderTextField(TEXT_FIELDS[0])}
      <Text style={styles.muted}>{t("fieldDateOfBirth")}</Text>
      <Text style={styles.muted}>{t("dobPrecision")}</Text>
      <Row>
        {(["exact", "month-year", "year"] as const).map((mode) => {
          const labels: Record<BirthMode, StringKey> = {
            exact: "dobExact",
            "month-year": "dobMonthYear",
            year: "dobYear",
          };
          return (
            <Button
              key={mode}
              kind={birthMode === mode ? "primary" : "secondary"}
              label={t(labels[mode])}
              onPress={() => chooseBirthMode(mode)}
            />
          );
        })}
      </Row>
      {birthMode === "exact" ? (
        <View style={{ gap: 4 }}>
          <NativeRegistrationFieldControl
            field="date_of_birth"
            label={t("fieldDateOfBirth")}
            value={fields.date_of_birth ?? ""}
            onChange={set("date_of_birth")}
            issue={errors.date_of_birth}
            onIssue={(issue) => setFieldIssue("date_of_birth", issue)}
          />
          {errorFor("date_of_birth")}
        </View>
      ) : null}
      {birthMode === "month-year" || birthMode === "year" ? (
        <View style={{ gap: 4 }}>
          <NativeRegistrationFieldControl
            field="date_of_birth_partial"
            label={t("fieldDateOfBirth")}
            value={fields.date_of_birth_partial ?? ""}
            onChange={set("date_of_birth_partial")}
            issue={errors.date_of_birth_partial}
            onIssue={(issue) => setFieldIssue("date_of_birth_partial", issue)}
            appearance={birthMode}
          />
          {errorFor("date_of_birth_partial")}
        </View>
      ) : null}
      {(() => {
        const display = calculateRegistrationAge(fields);
        return display ? (
          <Text style={styles.muted}>{formatRegistrationAge(display)}</Text>
        ) : null;
      })()}
      {birthMode !== "exact" ? (
        <View style={{ gap: 4 }}>
          <Text style={styles.muted}>{t("fieldAge")}</Text>
          <NativeRegistrationFieldControl
            field="age_years"
            label={t("fieldAge")}
            value={fields.age_years ?? ""}
            onChange={set("age_years")}
            issue={errors.age_years}
            onIssue={(issue) => setFieldIssue("age_years", issue)}
          />
          {errorFor("age_years")}
        </View>
      ) : null}
      <Text style={styles.muted}>{t("fieldSex")}</Text>
      <Row>
        {SEX_VALUES.map((sex) => (
          <Button
            key={sex}
            kind={fields.deceased_sex === sex ? "primary" : "secondary"}
            label={t(SEX_LABELS[sex])}
            onPress={() => set("deceased_sex")(sex)}
          />
        ))}
      </Row>
      {errorFor("deceased_sex")}
      {renderTextField(TEXT_FIELDS[1])}
      {TEXT_FIELDS.slice(2).map(renderTextField)}
      {message ? (
        <Text style={styles.error} accessibilityRole="alert">
          {message}
        </Text>
      ) : null}
      {ageConfirmationPending ? (
        <View style={styles.card} accessibilityRole="alert">
          <Text style={styles.text}>{t("ageReviewConfirm")}</Text>
          <Row>
            <Button
              kind="secondary"
              label={t("cancel")}
              disabled={busy}
              onPress={() => {
                setAgeConfirmationPending(false);
                setAgeConfirmationStartAfter(false);
              }}
            />
            <Button
              loading={busy}
              disabled={busy}
              label={t("ageReviewSave")}
              onPress={() => void save(ageConfirmationStartAfter, true)}
            />
          </Row>
        </View>
      ) : null}
      <Row>
        <Button
          label={t("save")}
          disabled={!db || !target || busy || ageConfirmationPending}
          onPress={() => void save(false)}
        />
        <Button
          label={t("registerSaveStart")}
          disabled={!db || !target || busy || ageConfirmationPending}
          onPress={() => void save(true)}
        />
        <Button
          kind="secondary"
          label={t("cancel")}
          disabled={busy}
          onPress={() => router.back()}
        />
      </Row>
    </Screen>
  );
}
