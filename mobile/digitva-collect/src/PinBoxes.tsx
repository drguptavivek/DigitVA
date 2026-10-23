/**
 * The PIN as six boxes, one digit each (docs/policy/mobile-sign-in.md section 9). The PIN is one string in the
 * parent; the boxes only show it. Typing fills left to right and moves on, backspace on an empty box steps back, a
 * pasted run of digits fills every box, and a wrong PIN (the parent bumps `shakeSignal` and clears `value`) shakes
 * the row. Masked unless Show is on; the numeric keypad opens at once.
 */
import { useEffect, useRef, useState } from "react";
import { Animated, Pressable, Text, TextInput, View, type NativeSyntheticEvent, type TextInputKeyPressEventData } from "react-native";

import { t } from "./i18n";
import { useUiStyles } from "./ui";

export const PIN_BOXES = 6;

/**
 * The PIN after text `text` arrived in box `index`, and the box to focus next. More than one digit is a paste (or a
 * keyboard sending the old and new digit together when the box already held one): a paste replaces the whole PIN,
 * a typed digit replaces the box's old one. Typing never leaves a gap: it lands at the first empty box at most.
 */
export function applyPinInput(value: string, index: number, text: string): { value: string; focus: number } {
  const digits = text.replace(/\D/g, "");
  let next: string;
  if (digits.length === 0) {
    next = value.slice(0, index) + value.slice(index + 1);
  } else if (digits.length > 1 && !(digits.length === 2 && index < value.length)) {
    next = digits.slice(0, PIN_BOXES);
  } else {
    const typed = digits.length === 2 ? (digits[0] === value[index] ? digits[1] : digits[0]) : digits;
    const at = Math.min(index, value.length);
    next = (value.slice(0, at) + typed + value.slice(at + 1)).slice(0, PIN_BOXES);
    return { value: next, focus: Math.min(at + 1, PIN_BOXES - 1) };
  }
  return { value: next, focus: Math.min(digits.length === 0 ? index : next.length, PIN_BOXES - 1) };
}

/** Backspace on an empty box: drop the last digit and step back to its box. */
export function backspaceFromEmpty(value: string): { value: string; focus: number } {
  return { value: value.slice(0, -1), focus: Math.max(value.length - 1, 0) };
}

export function PinBoxes({
  value,
  onChange,
  label,
  shakeSignal = 0,
  autoFocus = true
}: {
  value: string;
  onChange: (value: string) => void;
  /** Accessibility name of the row, e.g. "PIN"; each box is "<label> 1 of 6". */
  label: string;
  /** Changing this to a new non-zero number shakes the row. */
  shakeSignal?: number;
  autoFocus?: boolean;
}) {
  const styles = useUiStyles();
  const refs = useRef<(TextInput | null)[]>([]);
  const [shown, setShown] = useState(false);
  const shake = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (!shakeSignal) return;
    Animated.sequence([6, -6, 4, -4, 0].map((to) => Animated.timing(shake, { toValue: to, duration: 50, useNativeDriver: true }))).start();
    refs.current[0]?.focus();
  }, [shakeSignal, shake]);

  function change(result: { value: string; focus: number }) {
    onChange(result.value);
    refs.current[result.focus]?.focus();
  }

  return (
    <View accessibilityLabel={label} style={{ gap: 8 }}>
      <Animated.View style={{ flexDirection: "row", gap: 8, transform: [{ translateX: shake }] }}>
        {Array.from({ length: PIN_BOXES }, (_, index) => (
          <TextInput
            key={index}
            ref={(node) => {
              refs.current[index] = node;
            }}
            testID={`pin-box-${index}`}
            accessibilityLabel={`${label} ${index + 1} / ${PIN_BOXES}`}
            style={[styles.input, { flex: 1, minWidth: 0, textAlign: "center", paddingHorizontal: 0, fontSize: 22 }]}
            keyboardType="number-pad"
            inputMode="numeric"
            secureTextEntry={!shown}
            autoFocus={autoFocus && index === 0}
            autoComplete="off"
            autoCorrect={false}
            selectTextOnFocus
            value={value[index] ?? ""}
            onChangeText={(text) => change(applyPinInput(value, index, text))}
            onKeyPress={(event: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
              if (event.nativeEvent.key === "Backspace" && index >= value.length && value.length > 0) change(backspaceFromEmpty(value));
            }}
          />
        ))}
      </Animated.View>
      <Pressable accessibilityRole="button" onPress={() => setShown((on) => !on)} hitSlop={8}>
        <Text style={styles.muted}>{shown ? t("pinHide") : t("pinShow")}</Text>
      </Pressable>
    </View>
  );
}
