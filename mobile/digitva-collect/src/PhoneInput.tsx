import { useState } from "react";
import { Text, TextInput, View } from "react-native";

import { t } from "./i18n";
import { normalisePhone, PHONE_PLACEHOLDER, phoneDigits, phoneDisplay } from "./phoneFormat";
import { Button, useUiStyles } from "./ui";

type PhoneKey = "informant_phone" | "informant_phone_2";

/**
 * One phone input. *value* holds plain digits (what is stored and sent), the
 * field shows them 3-3-4. *onValidity* reports the blur check; the caller
 * blocks submit while a number is invalid.
 */
export function PhoneField({ label, value, error, disabled, onChange, onValidity }: {
  label: string;
  value: string;
  error?: string;
  disabled?: boolean;
  onChange: (digits: string) => void;
  onValidity?: (valid: boolean) => void;
}) {
  const styles = useUiStyles();
  return (
    <View style={{ gap: 4 }}>
      <TextInput
        accessibilityLabel={label}
        autoCorrect={false}
        inputMode="tel"
        keyboardType="phone-pad"
        placeholder={PHONE_PLACEHOLDER}
        style={styles.input}
        editable={!disabled}
        value={phoneDisplay(value)}
        onChangeText={(text) => onChange(phoneDigits(text, value))}
        onBlur={() => onValidity?.(!value || normalisePhone(value) !== null)}
      />
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
    </View>
  );
}

/**
 * The informant's numbers: "Phone number", and a second one revealed by
 * "Add another number" (or shown when it already has a value). Both optional.
 */
export function PhoneNumbers({ values, errors, disabled, onChange, onValidity }: {
  values: Record<PhoneKey, string>;
  errors: Partial<Record<PhoneKey, string | undefined>>;
  disabled?: boolean;
  onChange: (key: PhoneKey, digits: string) => void;
  onValidity: (key: PhoneKey, valid: boolean) => void;
}) {
  const styles = useUiStyles();
  const [revealed, setRevealed] = useState(false);
  const field = (key: PhoneKey, label: string) => (
    <View key={key} style={{ gap: 4 }}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <PhoneField
        label={label}
        value={values[key]}
        error={errors[key]}
        disabled={disabled}
        onChange={(digits) => onChange(key, digits)}
        onValidity={(valid) => onValidity(key, valid)}
      />
    </View>
  );
  return (
    <View style={{ gap: 8 }}>
      {field("informant_phone", t("fieldPhoneNumber"))}
      {revealed || values.informant_phone_2 ? (
        field("informant_phone_2", t("fieldInformantPhone2"))
      ) : disabled ? null : (
        <Button kind="secondary" label={t("addAnotherNumber")} onPress={() => setRevealed(true)} />
      )}
    </View>
  );
}
