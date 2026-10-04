import { useRouter } from "expo-router";
import { useEffect, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { getIntakeContext, INTAKE_API, registerDeath, startDraft, type IntakeBootstrap, type RegistrationInput } from "../client/api";
import { useAppState } from "../AppState";
import { localToday, registrationNeedsAgeConfirmation, validateRegistration, type RegistrationFields } from "../cases";
import { t, type StringKey } from "../i18n";
import { calculateRegistrationAge } from "../registrationAgeDisplay";
import { formatRegistrationAge } from "../registrationAgeText";
import { Button, useUiStyles } from "../ui";
import { browserErrorText, WebShell } from "./common";
import { RegistrationFieldControl, type RegistrationDateAppearance } from "./registrationControls";

const FIELD_DEFINITIONS: Array<{ key: keyof RegistrationInput; label: StringKey; help?: StringKey }> = [
  { key: "deceased_name", label: "fieldDeceasedName" },
  { key: "date_of_death", label: "fieldDateOfDeath" },
  { key: "address", label: "fieldAddress" },
  { key: "informant_name", label: "fieldInformantName" },
  { key: "informant_phone", label: "fieldInformantPhone" },
  { key: "remarks", label: "fieldRemarks", help: "remarksHelp" }
];

type DraftIssue = { code?: StringKey; message: string };

function draftIssueFor(key: keyof RegistrationInput, message: string): DraftIssue {
  const code = key === "date_of_death" || key === "date_of_birth" || key === "date_of_birth_partial"
    ? "errDate"
    : key === "age_years"
      ? "errAge"
      : undefined;
  return { code, message };
}

export default function DeathRegistrationScreen() {
  const router = useRouter();
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const [intake, setIntake] = useState<IntakeBootstrap>();
  const [projectId, setProjectId] = useState("");
  const [siteId, setSiteId] = useState("");
  const [orgUnitId, setOrgUnitId] = useState("");
  const [sex, setSex] = useState("");
  const [fields, setFields] = useState<Partial<RegistrationInput>>({});
  const [birthMode, setBirthMode] = useState<RegistrationDateAppearance>("exact");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [validationIssues, setValidationIssues] = useState<Partial<Record<keyof RegistrationInput, StringKey>>>({});
  const [draftIssues, setDraftIssues] = useState<Partial<Record<keyof RegistrationInput, DraftIssue>>>({});
  const [ageConfirmationPending, setAgeConfirmationPending] = useState(false);

  useEffect(() => {
    let active = true;
    setIntake(undefined);
    setProjectId("");
    setSiteId("");
    setOrgUnitId("");
    setMessage("");
    setValidationIssues({});
    setDraftIssues({});
    if (!bootstrap) return () => { active = false; };
    void getIntakeContext(bootstrap.csrf)
      .then(async (next) => {
        if (!active) return;
        const contexts = next.context.filter((entry) => entry.web_intake_mode === "death_register" || entry.web_intake_mode === "both");
        const scoped = { ...next, context: contexts };
        setIntake(scoped);
        const first = scoped.context[0];
        if (first) {
          setProjectId(first.project_id);
          setSiteId(first.site_id);
        }
      })
      .catch((error) => {
        if (active) setMessage(browserErrorText(error));
      });
    return () => {
      active = false;
    };
  }, [bootstrap]);

  const context = useMemo(
    () => intake?.context.find((entry) => entry.project_id === projectId && entry.site_id === siteId),
    [intake, projectId, siteId]
  );

  const ageDisplay = calculateRegistrationAge({
    date_of_death: fields.date_of_death ?? "",
    date_of_birth: fields.date_of_birth,
    date_of_birth_partial: fields.date_of_birth_partial
  });

  function updateField(key: keyof RegistrationInput, value: string) {
    setFields((previous) => ({ ...previous, [key]: value }));
    setValidationIssues((previous) => (previous[key] ? { ...previous, [key]: undefined } : previous));
    setDraftIssues((previous) => (previous[key] ? { ...previous, [key]: undefined } : previous));
    setAgeConfirmationPending(false);
  }

  function updateFieldIssue(key: keyof RegistrationInput, issue?: string) {
    setDraftIssues((previous) => {
      if (!issue) {
        if (!previous[key]) return previous;
        return { ...previous, [key]: undefined };
      }
      return { ...previous, [key]: draftIssueFor(key, issue) };
    });
  }

  function chooseBirthMode(next: RegistrationDateAppearance) {
    setAgeConfirmationPending(false);
    setBirthMode(next);
    setFields((previous) => ({
      ...previous,
      date_of_birth: next === "exact" && birthMode === "exact" ? previous.date_of_birth : undefined,
      date_of_birth_partial: next === birthMode ? previous.date_of_birth_partial : undefined,
      age_years: next === "exact" ? undefined : previous.age_years
    }));
    setValidationIssues((previous) => ({
      ...previous,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined
    }));
    setDraftIssues((previous) => ({
      ...previous,
      date_of_birth: undefined,
      date_of_birth_partial: undefined,
      age_years: undefined
    }));
  }

  function issueMessage(key: keyof RegistrationInput): string | undefined {
    const code = validationIssues[key] ?? draftIssues[key]?.code;
    return code ? t(code) : draftIssues[key]?.message;
  }

  const renderField = (field: (typeof FIELD_DEFINITIONS)[number]) => (
    <View key={field.key}>
      <Text style={styles.muted}>{t(field.label)}</Text>
      <RegistrationFieldControl
        field={field.key}
        label={t(field.label)}
        value={String(fields[field.key] ?? "")}
        onChange={(value) => updateField(field.key, value)}
        issueMessage={issueMessage(field.key)}
        onIssue={(issue) => updateFieldIssue(field.key, issue)}
      />
      {field.help ? <Text style={styles.muted}>{t(field.help)}</Text> : null}
    </View>
  );

  async function submit(confirmAge = false) {
    if (!bootstrap || !intake || !context) return;
    setMessage("");
    const validationFields = {
      ...fields,
      deceased_name: fields.deceased_name ?? "",
      deceased_sex: sex,
      date_of_death: fields.date_of_death ?? ""
    } as RegistrationFields;
    const validation = validateRegistration(validationFields, localToday());
    const nextIssues: Partial<Record<keyof RegistrationInput, StringKey>> = {};
    for (const [key, issue] of Object.entries(validation)) {
      nextIssues[key as keyof RegistrationInput] = issue as StringKey;
    }
    const birthField = birthMode === "exact" ? "date_of_birth" : "date_of_birth_partial";
    const birthValue = validationFields[birthField];
    if (!birthValue?.trim()) nextIssues[birthField] = "errRequired";
    setValidationIssues(nextIssues);
    if (Object.values(nextIssues).some(Boolean) || Object.values(draftIssues).some(Boolean)) {
      setAgeConfirmationPending(false);
      setMessage(t("registerFixErrors"));
      return;
    }
    if (!confirmAge && registrationNeedsAgeConfirmation(validationFields)) {
      setAgeConfirmationPending(true);
      return;
    }
    setAgeConfirmationPending(false);
    setBusy(true);
    try {
      const deathsLink = `${INTAKE_API}/deaths`;
      const registration = await registerDeath(
        deathsLink,
        {
          project_id: projectId,
          site_id: siteId,
          ...(orgUnitId ? { org_unit_id: orgUnitId } : {}),
          deceased_name: (fields.deceased_name ?? "").trim(),
          deceased_sex: sex,
          date_of_death: (fields.date_of_death ?? "").trim(),
          ...Object.fromEntries(
            Object.entries(fields).filter(
              ([key, value]) =>
                !["deceased_name", "date_of_death"].includes(key) && typeof value === "string" && value.trim() !== ""
            )
          )
        } as RegistrationInput,
        bootstrap.csrf
      );
      const draft = await startDraft(
        bootstrap.links.intakeDrafts,
        {
          project_id: projectId,
          site_id: siteId,
          ...(orgUnitId ? { org_unit_id: orgUnitId } : {}),
          death_id: registration.case.death_id
        },
        bootstrap.csrf
      );
      router.replace({ pathname: "/interview", params: { draftId: draft.draft.draft_id } });
    } catch (error) {
      setMessage(browserErrorText(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <WebShell title={t("registrationTitle")}>
      {intake?.context.length ? (
        <>
          <Text style={styles.muted}>{t("chooseSite")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {intake.context.map((entry) => (
              <Button
                key={`${entry.project_id}:${entry.site_id}`}
                kind={entry.project_id === projectId && entry.site_id === siteId ? "primary" : "secondary"}
                label={`${entry.project_name ?? entry.project_id} · ${entry.site_name ?? entry.site_id}`}
                onPress={() => {
                  setProjectId(entry.project_id);
                  setSiteId(entry.site_id);
                  setOrgUnitId("");
                }}
              />
            ))}
          </View>
          {context?.org_units?.filter((unit) => unit.selectable !== false).length ? (
            <View>
              <Text style={styles.muted}>{t("chooseUnit")}</Text>
              <View style={styles.row} accessibilityRole="radiogroup">
                {context.org_units.filter((unit) => unit.is_active !== false && unit.selectable !== false).map((unit) => (
                  <Button
                    key={unit.org_unit_id}
                    kind={unit.org_unit_id === orgUnitId ? "primary" : "secondary"}
                    label={unit.unit_name ?? unit.unit_code ?? unit.org_unit_id}
                    onPress={() => setOrgUnitId(unit.org_unit_id)}
                  />
                ))}
              </View>
            </View>
          ) : null}
          {renderField(FIELD_DEFINITIONS[0])}
          <Text style={styles.muted}>{t("fieldDateOfBirth")}</Text>
          <Text style={styles.muted}>{t("dobPrecision")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {(
              [
                ["exact", "dobExact"],
                ["month-year", "dobMonthYear"],
                ["year", "dobYear"]
              ] as const
            ).map(([mode, label]) => (
              <Button
                key={mode}
                kind={birthMode === mode ? "primary" : "secondary"}
                label={t(label)}
                onPress={() => chooseBirthMode(mode)}
              />
            ))}
          </View>
          {birthMode === "exact" ? (
            <RegistrationFieldControl
              field="date_of_birth"
              label={t("fieldDateOfBirth")}
              value={String(fields.date_of_birth ?? "")}
              onChange={(value) => updateField("date_of_birth", value)}
              issueMessage={issueMessage("date_of_birth")}
              onIssue={(issue) => updateFieldIssue("date_of_birth", issue)}
              dateAppearance="exact"
            />
          ) : null}
          {birthMode === "month-year" || birthMode === "year" ? (
            <RegistrationFieldControl
              field="date_of_birth_partial"
              label={t("fieldDateOfBirth")}
              value={String(fields.date_of_birth_partial ?? "")}
              onChange={(value) => updateField("date_of_birth_partial", value)}
              issueMessage={issueMessage("date_of_birth_partial")}
              onIssue={(issue) => updateFieldIssue("date_of_birth_partial", issue)}
              dateAppearance={birthMode}
            />
          ) : null}
          {ageDisplay ? <Text style={styles.muted}>{formatRegistrationAge(ageDisplay)}</Text> : null}
          {birthMode !== "exact" ? (
            <View>
              <Text style={styles.muted}>{t("fieldAge")}</Text>
              <RegistrationFieldControl
                field="age_years"
                label={t("fieldAge")}
                value={String(fields.age_years ?? "")}
                onChange={(value) => updateField("age_years", value)}
                issueMessage={issueMessage("age_years")}
                onIssue={(issue) => updateFieldIssue("age_years", issue)}
              />
            </View>
          ) : null}
          <Text style={styles.muted}>{t("fieldSex")}</Text>
          <View style={styles.row} accessibilityRole="radiogroup">
            {(["male", "female", "undetermined", "unknown"] as const).map((value) => (
              <Button
                key={value}
                kind={sex === value ? "primary" : "secondary"}
                label={t(`sex${value[0].toUpperCase()}${value.slice(1)}` as "sexMale")}
                onPress={() => {
                  setSex(value);
                  setValidationIssues((previous) => ({ ...previous, deceased_sex: undefined }));
                  setAgeConfirmationPending(false);
                }}
              />
            ))}
          </View>
          {issueMessage("deceased_sex") ? (
            <Text style={styles.error} accessibilityRole="alert">{issueMessage("deceased_sex")}</Text>
          ) : null}
          {FIELD_DEFINITIONS.slice(1).map(renderField)}
          {message ? <Text style={styles.error} accessibilityRole="alert">{message}</Text> : null}
          {ageConfirmationPending ? (
            <View style={styles.card} accessibilityRole="alert">
              <Text style={styles.text}>{t("ageReviewConfirm")}</Text>
              <View style={styles.row}>
                <Button kind="secondary" label={t("cancel")} onPress={() => setAgeConfirmationPending(false)} />
                <Button loading={busy} disabled={busy} label={t("ageReviewSave")} onPress={() => void submit(true)} />
              </View>
            </View>
          ) : null}
          <Button loading={busy} disabled={busy || ageConfirmationPending} label={t("registerSaveStart")} onPress={() => void submit()} />
          <Button kind="secondary" label={t("cancel")} onPress={() => router.back()} />
        </>
      ) : (
        <Text style={styles.muted}>{message || t("noSites")}</Text>
      )}
    </WebShell>
  );
}
