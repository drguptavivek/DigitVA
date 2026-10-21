import { useRef, useState } from "react";
import { Platform, Text, TextInput, View } from "react-native";

import { t } from "./i18n";
import { checkIdentifier, typedCaret, type IdentifierRule, type IdentifierType } from "./identifiers";
import { Button, useUiStyles } from "./ui";

/** The number's face; the theme has no monospace token. */
export const MONOSPACE = Platform.select({ web: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace", ios: "Menlo", default: "monospace" });

/** The advice text for a broken rule (never echoes the value). */
export function identifierIssueText(type: IdentifierType, rule: IdentifierRule | "required"): string {
  const label = type.label;
  if (rule === "required") return t("idErrRequired", { label });
  if (rule === "length") {
    return type.min_length === type.max_length
      ? t("idErrLengthExact", { label, min: type.min_length })
      : t("idErrLength", { label, min: type.min_length, max: type.max_length });
  }
  if (rule === "char_type") {
    const key = {
      digits: "idErrDigits",
      letters: "idErrLetters",
      letters_digits: "idErrLettersDigits",
      letters_digits_hyphen_slash: "idErrLettersDigitsHyphenSlash",
    }[type.char_type ?? "letters_digits"] as "idErrDigits";
    return t(key, { label });
  }
  return type.example ? t("idErrPatternExample", { label, example: type.example }) : t("idErrPattern", { label });
}

function IdentifierRow({ type, value, onChange, error, warning, onContinue, onEdit, disabled }: {
  type: IdentifierType;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  warning?: string;
  onContinue?: () => void;
  onEdit?: () => void;
  disabled?: boolean;
}) {
  const styles = useUiStyles();
  // The selection before the keystroke (onChangeText fires before onSelectionChange). It is only
  // forced for one render when the transform changed the text, so the caret follows the edit.
  const lastSelection = useRef({ start: value.length, end: value.length });
  const [forced, setForced] = useState<{ start: number; end: number } | undefined>();
  const rule = value ? checkIdentifier(type, value) : undefined;
  const advice = error || (rule ? identifierIssueText(type, rule) : "");
  const labelText = type.required_at_report ? `${type.label} *` : type.label;
  const a11yLabel = type.required_at_report ? t("idRequiredA11y", { label: type.label }) : type.label;
  return (
    <View style={{ gap: 4, minWidth: 0 }} testID={`identifier-${type.code}`}>
      <Text style={styles.fieldLabel}>{labelText}</Text>
      <TextInput
        accessibilityLabel={a11yLabel}
        testID={`identifier-input-${type.code}`}
        value={value}
        editable={!disabled}
        autoCapitalize="characters"
        autoCorrect={false}
        spellCheck={false}
        maxLength={type.max_length + 8}
        selection={forced}
        onSelectionChange={(event) => {
          lastSelection.current = event.nativeEvent.selection;
          setForced(undefined);
        }}
        onChangeText={(text) => {
          const next = typedCaret(value, lastSelection.current, text);
          if (next.caret !== undefined) {
            lastSelection.current = { start: next.caret, end: next.caret };
            setForced(lastSelection.current);
          }
          onChange(next.value);
        }}
        style={[styles.input, { fontFamily: MONOSPACE, minWidth: 0, maxWidth: "100%" }]}
      />
      {type.example ? <Text style={styles.muted}>{t("idExample", { example: type.example })}</Text> : null}
      {advice ? <Text style={styles.error} accessibilityRole="alert">{advice}</Text> : null}
      {warning ? (
        <View accessibilityRole="alert" style={{ gap: 4 }}>
          <Text style={styles.text}>{warning}</Text>
          <View style={styles.row}>
            <ActionButton label={t("idWarnContinue")} onPress={onContinue} />
            <ActionButton label={t("idWarnEdit")} onPress={onEdit} />
          </View>
        </View>
      ) : null}
    </View>
  );
}

function ActionButton({ label, onPress }: { label: string; onPress?: () => void }) {
  return <Button size="sm" kind="secondary" label={label} onPress={onPress ?? (() => undefined)} />;
}

/**
 * One row per active type of the case's project: label, monospaced input, example hint, the rule or
 * server message under it, and a duplicate warning with Continue and Edit (a warning never blocks).
 * The client checks are advice; the caller decides whether a broken rule stops the submit.
 */
export function IdentifierFields({ types, values, onChange, errors = {}, warnings = {}, onContinue, onEdit, disabled }: {
  types: IdentifierType[];
  values: Record<string, string | undefined>;
  onChange: (code: string, value: string) => void;
  /** Server refusals per type code. */
  errors?: Record<string, string>;
  /** Duplicate warnings per type code. */
  warnings?: Record<string, string>;
  onContinue?: (code: string) => void;
  onEdit?: (code: string) => void;
  disabled?: boolean;
}) {
  const styles = useUiStyles();
  if (types.length === 0) return null;
  return (
    <View style={{ gap: 12, minWidth: 0 }} testID="identifier-fields">
      <Text style={styles.headline}>{t("idSectionTitle")}</Text>
      {[...types].sort((a, b) => a.sort_order - b.sort_order).map((type) => (
        <IdentifierRow
          key={type.code}
          type={type}
          value={values[type.code] ?? ""}
          onChange={(value) => onChange(type.code, value)}
          error={errors[type.code]}
          warning={warnings[type.code]}
          onContinue={() => onContinue?.(type.code)}
          onEdit={() => onEdit?.(type.code)}
          disabled={disabled}
        />
      ))}
    </View>
  );
}
