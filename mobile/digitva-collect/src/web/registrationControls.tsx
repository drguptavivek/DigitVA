import { Text, View } from "react-native";

import type { RegistrationInput } from "../client/api";
import { localToday } from "../cases";
import { t, uiLocale } from "../i18n";
import { MultilineInput } from "../MultilineInput";
import { PhoneField } from "../PhoneInput";
import { useUiStyles } from "../ui";
import { WhoVaQuestionControls, type LightweightAnswer, type WhoVaQuestionControlProps } from "../whoControls.web";
import { DateControl } from "../workspace/doris/DateControl.web";

type RegistrationField = keyof RegistrationInput;
export type RegistrationDateAppearance = "exact" | "month-year" | "year";

export type RegistrationFieldKind = "text" | "date" | "integer" | "phone" | "multiline";

const MULTILINE_FIELDS = new Set<RegistrationField>(["address", "remarks"]);

/** Keep registration controls aligned with the reusable WHO form primitives. */
export function registrationFieldKind(field: RegistrationField): RegistrationFieldKind {
  if (field === "date_of_death" || field === "date_of_birth" || field === "date_of_birth_partial") return "date";
  if (field === "age_years") return "integer";
  if (field === "informant_phone" || field === "informant_phone_2") return "phone";
  if (MULTILINE_FIELDS.has(field)) return "multiline";
  return "text";
}

type RegistrationQuestion = WhoVaQuestionControlProps["question"] & Record<string, unknown> & {
  control: "date" | "integer" | "text";
  dataType: "date" | "number" | "string";
};

type RegistrationIssue = { question: string; code: string; message: string };

function questionFor(
  field: RegistrationField,
  label: string,
  locale: string,
  control: RegistrationQuestion["control"],
  appearance?: string
): RegistrationQuestion {
  return {
    name: field,
    order: 0,
    sourceRow: 0,
    sourceType: "digitva-registration",
    dataType: control === "date" ? "date" : control === "integer" ? "number" : "string",
    control,
    label: { en: label, [locale]: label },
    hint: {},
    guidance: {},
    required: field === "deceased_name" || field === "date_of_death",
    readOnly: false,
    constraintMessage: {},
    sectionPath: [],
    ...(appearance ? { appearance } : {})
  };
}

function controlProps(
  question: RegistrationQuestion,
  value: LightweightAnswer,
  onAnswer: (next: LightweightAnswer) => void,
  locale: string,
  issues: RegistrationIssue[]
): WhoVaQuestionControlProps {
  return {
    question,
    value,
    data: {},
    locale,
    issues,
    onAnswer
  };
}

export function RegistrationFieldControl({
  field,
  label,
  value,
  onChange,
  issueMessage,
  onIssue,
  dateAppearance = "exact"
}: {
  field: RegistrationField;
  label: string;
  value: string;
  onChange: (value: string) => void;
  issueMessage?: string;
  onIssue?: (message?: string) => void;
  dateAppearance?: RegistrationDateAppearance;
}) {
  const styles = useUiStyles();
  const locale = uiLocale();
  const kind = registrationFieldKind(field);
  const question = questionFor(
    field,
    label,
    locale,
    kind === "date" ? "date" : kind === "integer" ? "integer" : "text",
    dateAppearance === "exact" ? undefined : dateAppearance
  );
  const issues: RegistrationIssue[] = issueMessage
    ? [{ question: field, code: "constraint", message: issueMessage }]
    : [];
  const onAnswer = (next: LightweightAnswer) => {
    if (kind === "integer" && typeof next === "number" && (next < 0 || next > 125)) {
      onChange(String(next));
      onIssue?.(t("errAge"));
      return;
    }
    onChange(next == null ? "" : String(next));
    onIssue?.();
  };

  // Date of birth uses the browser's own controls by precision; the value formats stay YYYY-MM-DD, YYYY-MM and YYYY.
  if (field === "date_of_birth" || field === "date_of_birth_partial") {
    return (
      <View>
        <DateControl precision={dateAppearance === "year" ? "year" : dateAppearance === "month-year" ? "month" : "date"} label={label} value={value} placeholder={t("dobSelectYear")} error={Boolean(issueMessage)} onChange={(next) => { onChange(next); onIssue?.(); }} />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  // Date of death shares the birth-date control; validateRegistration still enforces required and no-future-date on submit.
  if (field === "date_of_death") {
    return (
      <View>
        <DateControl precision="date" label={label} value={value} max={localToday()} error={Boolean(issueMessage)} onChange={(next) => { onChange(next); onIssue?.(); }} />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  if (kind === "date") {
    return (
      <View>
        <DateControl
          precision={dateAppearance === "year" ? "year" : dateAppearance === "month-year" ? "month" : "date"}
          label={label}
          value={value}
          placeholder={t("dobSelectYear")}
          error={Boolean(issueMessage)}
          onChange={(next) => { onChange(next); onIssue?.(); }}
        />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  if (kind === "integer") {
    return (
      <View>
        <WhoVaQuestionControls.Integer {...controlProps(question, value ? Number(value) : undefined, onAnswer, locale, issues)} />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  if (kind === "phone") {
    return (
      <View>
        <PhoneField
          label={label}
          value={value}
          error={issueMessage}
          onChange={onChange}
          onValidity={(valid) => onIssue?.(valid ? undefined : t("errPhone"))}
        />
      </View>
    );
  }
  if (kind === "multiline") {
    return (
      <View>
        <MultilineInput label={label} value={value} onChange={(next) => { onChange(next); onIssue?.(); }} />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  return (
    <View>
      <WhoVaQuestionControls.Text {...controlProps(question, value || undefined, onAnswer, locale, issues)} />
      {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
    </View>
  );
}
