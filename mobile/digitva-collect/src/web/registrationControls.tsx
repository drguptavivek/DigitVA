import { WhoVaQuestionControls, type WhoVaQuestionControlProps } from "@drguptavivek/who-2022-va/web";
import {
  resolveUiMessages,
  WHO_VA_BUILT_IN_UI_TRANSLATIONS,
  type AnswerValue,
  type InstrumentQuestion,
  type QuestionControl,
  type ValidationIssue
} from "@drguptavivek/who-2022-va";
import { Platform, Text, TextInput, View } from "react-native";

import type { RegistrationInput } from "../client/api";
import { t, uiLocale } from "../i18n";
import { useUiStyles } from "../ui";
import { useTheme } from "../theme";

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

function questionFor(
  field: RegistrationField,
  label: string,
  locale: string,
  control: QuestionControl,
  appearance?: string
): InstrumentQuestion {
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
  question: InstrumentQuestion,
  value: AnswerValue | undefined,
  onAnswer: (next: AnswerValue | undefined) => void,
  locale: string,
  issues: ValidationIssue[]
): WhoVaQuestionControlProps {
  return {
    question,
    value,
    data: {},
    locale,
    messages: resolveUiMessages(locale, WHO_VA_BUILT_IN_UI_TRANSLATIONS),
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
  const theme = useTheme();
  const locale = uiLocale();
  const kind = registrationFieldKind(field);
  const question = questionFor(
    field,
    label,
    locale,
    kind === "date" ? "date" : kind === "integer" ? "integer" : "text",
    kind === "multiline" ? "multiline" : dateAppearance === "exact" ? undefined : dateAppearance
  );
  const issues: ValidationIssue[] = issueMessage
    ? [{ question: field, code: "constraint", message: issueMessage }]
    : [];
  const onAnswer = (next: AnswerValue | undefined) => {
    if (kind === "integer" && typeof next === "number" && (next < 0 || next > 125)) {
      onChange(String(next));
      onIssue?.(t("errAge"));
      return;
    }
    onChange(next == null ? "" : String(next));
    onIssue?.();
  };
  const controlValue =
    kind !== "date" || dateAppearance === "exact"
      ? value
      : dateAppearance === "month-year" && /^\d{4}-\d{2}$/.test(value)
        ? `${value}-01`
        : dateAppearance === "year" && /^\d{4}$/.test(value)
          ? `${value}-01-01`
          : "";
  const onDateAnswer = (next: AnswerValue | undefined) => {
    if (next == null || typeof next !== "string") {
      onChange("");
      return;
    }
    if (dateAppearance === "month-year") onChange(/^\d{4}-\d{2}-\d{2}$/.test(next) ? next.slice(0, 7) : "");
    else if (dateAppearance === "year") onChange(/^\d{4}-\d{2}-\d{2}$/.test(next) ? next.slice(0, 4) : "");
    else onChange(next);
  };
  const themed = Platform.OS === "web" ? ({
    "--who-2022-web-color-brand": theme.colors.accent,
    "--who-2022-web-color-brand-deep": theme.colors.accentPressed,
    "--who-2022-web-color-brand-soft": theme.colors.accentSoft,
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
    "--who-2022-web-color-danger-soft": theme.colors.dangerSoft
  } as unknown as Record<string, string>) : undefined;

  if (kind === "date") {
    return (
      <View style={themed}>
      <WhoVaQuestionControls.Date
        {...controlProps(question, controlValue || undefined, dateAppearance === "exact" ? onAnswer : onDateAnswer, locale, issues)}
        onDraftIssue={(_draft, issue) => onIssue?.(issue?.message)}
      />
      {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  if (kind === "integer") {
    return (
      <View style={themed}>
        <WhoVaQuestionControls.Integer {...controlProps(question, value ? Number(value) : undefined, onAnswer, locale, issues)} />
        {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  if (kind === "phone") {
    return (
      <View style={themed}>
      <TextInput
        accessibilityLabel={label}
        autoCorrect={false}
        inputMode="tel"
        keyboardType="phone-pad"
        style={styles.input}
        value={value}
        onChangeText={onChange}
      />
      {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
      </View>
    );
  }
  return (
    <View style={themed}>
      <WhoVaQuestionControls.Text {...controlProps(question, value || undefined, onAnswer, locale, issues)} />
      {issueMessage ? <Text style={styles.error} accessibilityRole="alert">{issueMessage}</Text> : null}
    </View>
  );
}
