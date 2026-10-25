/**
 * Lightweight browser controls for coding, supervision and registration.
 *
 * The interview keeps the full WHO renderer behind its deferred boundary. These
 * controls intentionally only cover the small choice/text primitives used by
 * the app-owned screens, so those screens do not pull the interview bundle in.
 */
import { Pressable, Text, TextInput, View } from "react-native";

import { useUiStyles } from "./ui";
import { useTheme } from "./theme";

type LocalizedLabel = { en?: string; [locale: string]: string | undefined };

type LightweightQuestion = {
  name: string;
  label?: LocalizedLabel;
  choices?: Array<{ value: string; label: LocalizedLabel }>;
  readOnly?: boolean;
  appearance?: string;
};

export type LightweightAnswer = string | number | boolean | string[] | null | undefined;

export type WhoVaQuestionControlProps = {
  question: LightweightQuestion;
  value: LightweightAnswer;
  data?: unknown;
  locale: string;
  showEnglish?: boolean;
  messages?: unknown;
  issues?: readonly unknown[];
  onAnswer: (value: LightweightAnswer) => void;
  onDraftIssue?: (questionName: string, issue: unknown) => void;
  choiceColumns?: number;
};

function localeCandidates(locale: string): string[] {
  const normalized = locale.trim().replaceAll("_", "-").toLowerCase();
  const language = normalized.split("-")[0] ?? "";
  return [...new Set([normalized, language, "en"].filter(Boolean))];
}

function labelText(label: LocalizedLabel | undefined, locale: string, fallback: string): string {
  if (!label) return fallback;
  for (const candidate of localeCandidates(locale)) {
    if (label[candidate]) return label[candidate] as string;
  }
  return Object.values(label).find((value): value is string => Boolean(value)) ?? fallback;
}

function questionLabel(question: LightweightQuestion, locale: string): string {
  return labelText(question.label, locale, question.name);
}

function questionIssues(issues: readonly unknown[] | undefined): boolean {
  return Boolean(issues?.length);
}

function ChoiceIndicator({ multiple, selected }: { multiple: boolean; selected: boolean }) {
  const theme = useTheme();
  return (
    <View
      aria-hidden={true}
      style={{
        width: 20,
        height: 20,
        borderRadius: multiple ? 4 : 10,
        borderWidth: 2,
        borderColor: selected ? theme.ui.primary : theme.ui.input,
        backgroundColor: selected ? theme.ui.primary : theme.ui.background,
        alignItems: "center",
        justifyContent: "center"
      }}
    >
      {selected ? <Text style={{ color: theme.ui.primaryForeground, fontSize: 14, lineHeight: 16 }}>{multiple ? "✓" : "•"}</Text> : null}
    </View>
  );
}

function TextControl({ question, value, locale, issues = [], onAnswer }: WhoVaQuestionControlProps) {
  const styles = useUiStyles();
  const readOnly = Boolean(question.readOnly);
  const multiline = question.appearance?.split(" ").includes("multiline") ?? false;
  const numbersOnly = question.appearance?.split(" ").includes("numbers") ?? false;
  return (
    <TextInput
      accessibilityLabel={questionLabel(question, locale)}
      testID={`question-${question.name}`}
      aria-invalid={questionIssues(issues) || undefined}
      aria-readonly={readOnly || undefined}
      editable={!readOnly}
      readOnly={readOnly || undefined}
      multiline={multiline}
      keyboardType={numbersOnly ? "number-pad" : "default"}
      value={value == null ? "" : String(value)}
      onChangeText={(next) => onAnswer(next || undefined)}
      style={[
        styles.input,
        multiline && { minHeight: 72, textAlignVertical: "top" },
        questionIssues(issues) && { borderColor: "#B42318" },
        readOnly && { opacity: 0.6 }
      ]}
    />
  );
}

function IntegerControl({ question, value, locale, issues = [], onAnswer }: WhoVaQuestionControlProps) {
  const styles = useUiStyles();
  const readOnly = Boolean(question.readOnly);
  const text = value == null ? "" : String(value);
  return (
    <TextInput
      accessibilityLabel={questionLabel(question, locale)}
      testID={`question-${question.name}`}
      aria-invalid={questionIssues(issues) || undefined}
      aria-readonly={readOnly || undefined}
      editable={!readOnly}
      readOnly={readOnly || undefined}
      keyboardType="number-pad"
      value={text}
      onChangeText={(typed) => {
        if (readOnly) return;
        const raw = typed.replace(/[^\d-]/g, "");
        if (!raw) onAnswer(undefined);
        else if (/^-?\d+$/.test(raw)) onAnswer(Number(raw));
      }}
      style={[styles.input, questionIssues(issues) && { borderColor: "#B42318" }, readOnly && { opacity: 0.6 }]}
    />
  );
}

function ChoiceControl({ multiple, question, value, locale, showEnglish, issues = [], choiceColumns, onAnswer }: WhoVaQuestionControlProps & { multiple: boolean }) {
  const styles = useUiStyles();
  const theme = useTheme();
  const readOnly = Boolean(question.readOnly);
  const selectedValues = Array.isArray(value) ? value.map(String) : [];
  const selected = typeof value === "string" ? value : undefined;
  const choices = question.choices ?? [];
  return (
    <View
      testID={`question-${question.name}-choices`}
      style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}
      accessibilityLabel={questionLabel(question, locale)}
    >
      {choices.map((choice) => {
        const isSelected = multiple ? selectedValues.includes(choice.value) : selected === choice.value;
        const label = labelText(choice.label, locale, choice.value);
        const english = showEnglish && locale.toLowerCase() !== "en" ? labelText(choice.label, "en", "") : "";
        return (
          <Pressable
            key={choice.value}
            accessibilityRole={multiple ? "checkbox" : "radio"}
            accessibilityLabel={`${questionLabel(question, locale)}: ${label}`}
            accessibilityState={multiple ? { checked: isSelected, disabled: readOnly } : { selected: isSelected, disabled: readOnly }}
            aria-invalid={questionIssues(issues) || undefined}
            disabled={readOnly}
            testID={`question-${question.name}-choice-${choice.value}`}
            onPress={() => {
              if (readOnly) return;
              if (multiple) {
                onAnswer(isSelected ? selectedValues.filter((item) => item !== choice.value) : [...selectedValues, choice.value]);
              } else {
                onAnswer(choice.value);
              }
            }}
            style={({ pressed }) => [
              styles.secondary,
              { flexDirection: "row", alignItems: "center", gap: 8, flexGrow: choiceColumns ? 1 : 0, flexBasis: choiceColumns ? `${100 / Math.max(1, choiceColumns)}%` : "100%", opacity: readOnly ? 0.6 : pressed ? 0.85 : 1 },
              isSelected && { backgroundColor: theme.ui.accent, borderColor: theme.ui.primary },
              questionIssues(issues) && { borderColor: theme.ui.destructiveText }
            ]}
          >
            <ChoiceIndicator multiple={multiple} selected={isSelected} />
            <Text style={styles.text}>{label}{english ? `\n${english}` : ""}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export const WhoVaQuestionControls = {
  Text: TextControl,
  Integer: IntegerControl,
  SingleChoice: (props: WhoVaQuestionControlProps) => <ChoiceControl {...props} multiple={false} />,
  MultipleChoice: (props: WhoVaQuestionControlProps) => <ChoiceControl {...props} multiple />
} as const;
