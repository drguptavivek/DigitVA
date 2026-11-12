/**
 * The PIN as six boxes, one digit each (docs/policy/mobile-sign-in.md section 9). The PIN is one string in the
 * parent; the boxes only show it. Typing fills left to right and moves on, backspace on an empty box steps back, a
 * pasted run of digits fills every box, and a wrong PIN (the parent bumps `shakeSignal` and clears `value`) shakes
 * the row. Masked unless Show (the eye at the trailing end of the row, centred on the boxes) is on; the numeric
 * keypad opens at once. Boxes are 48 x 56pt fills with no edge (growing with the text); only the box being typed in
 * has the focus ring.
 * `onFilled` fires when typing fills the last box, and bumping `focusSignal` focuses the first empty box, so a
 * parent moves on to the next row only once this one is full (Set PIN's Confirm row).
 * Development builds add one plain field (testID `pin-input`) that takes the whole PIN typed at once: test drivers
 * type faster than focus moves between boxes, and the boxes read a digit landing in a filled box as a correction.
 */
import { useEffect, useRef, useState } from "react";
import { Animated, Pressable, TextInput, View, type NativeSyntheticEvent, type TextInputKeyPressEventData } from "react-native";

import { t } from "./i18n";
import { useTheme } from "./theme";
import { useUiStyles } from "./ui";
import { StateIcon } from "./ui/StateView";

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
  autoFocus = true,
  onFilled,
  focusSignal = 0
}: {
  value: string;
  onChange: (value: string) => void;
  /** Accessibility name of the row, e.g. "PIN"; each box is "<label> 1 of 6". */
  label: string;
  /** Changing this to a new non-zero number shakes the row. */
  shakeSignal?: number;
  autoFocus?: boolean;
  /** Called when a typed or pasted digit fills the last box. */
  onFilled?: () => void;
  /** Changing this to a new non-zero number focuses the first empty box. */
  focusSignal?: number;
}) {
  const styles = useUiStyles();
  const { ui, textScale } = useTheme();
  const refs = useRef<(TextInput | null)[]>([]);
  const [shown, setShown] = useState(false);
  const [focusedBox, setFocusedBox] = useState<number>();
  const shake = useRef(new Animated.Value(0)).current;
  // The latest PIN, updated before onChange: digits typed faster than a re-render must build on each other, not on
  // the stale `value` prop (which put the second digit back into the first box).
  const valueRef = useRef(value);
  valueRef.current = value;

  useEffect(() => {
    if (!shakeSignal) return;
    Animated.sequence([6, -6, 4, -4, 0].map((to) => Animated.timing(shake, { toValue: to, duration: 50, useNativeDriver: true }))).start();
    refs.current[0]?.focus();
  }, [shakeSignal, shake]);

  useEffect(() => {
    if (focusSignal) refs.current[Math.min(valueRef.current.length, PIN_BOXES - 1)]?.focus();
  }, [focusSignal]);

  function change(result: { value: string; focus: number }) {
    const wasFull = valueRef.current.length === PIN_BOXES;
    valueRef.current = result.value;
    onChange(result.value);
    if (result.value.length === PIN_BOXES && !wasFull && onFilled) onFilled();
    else refs.current[result.focus]?.focus();
  }

  return (
    <View accessibilityLabel={label} style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
      <Animated.View style={{ flex: 1, flexDirection: "row", gap: 8, transform: [{ translateX: shake }] }}>
        {Array.from({ length: PIN_BOXES }, (_, index) => (
          <TextInput
            key={index}
            ref={(node) => {
              refs.current[index] = node;
            }}
            testID={`pin-box-${index}`}
            accessibilityLabel={`${label} ${index + 1} / ${PIN_BOXES}`}
            style={[styles.input, focusedBox === index && styles.inputFocused, { flex: 1, minWidth: 0, maxWidth: 48 * Math.max(1, textScale), height: 56 * Math.max(1, textScale), textAlign: "center", paddingHorizontal: 0, fontSize: 22 * textScale }]}
            onFocus={() => setFocusedBox(index)}
            onBlur={() => setFocusedBox((current) => (current === index ? undefined : current))}
            keyboardType="number-pad"
            inputMode="numeric"
            secureTextEntry={!shown}
            autoFocus={autoFocus && index === 0}
            autoComplete="off"
            importantForAutofill="no"
            autoCorrect={false}
            selectTextOnFocus
            value={value[index] ?? ""}
            onChangeText={(text) => change(applyPinInput(valueRef.current, index, text))}
            onKeyPress={(event: NativeSyntheticEvent<TextInputKeyPressEventData>) => {
              const current = valueRef.current;
              if (event.nativeEvent.key === "Backspace" && index >= current.length && current.length > 0) change(backspaceFromEmpty(current));
            }}
          />
        ))}
      </Animated.View>
      {__DEV__ ? (
        <TextInput
          testID="pin-input"
          accessibilityLabel={`${label} (dev)`}
          keyboardType="number-pad"
          autoComplete="off"
          importantForAutofill="no"
          style={{ width: 44, height: 44, opacity: 0.2 }}
          value=""
          onChangeText={(text) => change(applyPinInput("", 0, text.length === 1 ? valueRef.current + text : text))}
        />
      ) : null}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={shown ? t("pinHide") : t("pinShow")}
        onPress={() => setShown((on) => !on)}
        style={{ width: 44, minHeight: 44, alignItems: "center", justifyContent: "center" }}
      >
        <StateIcon name={shown ? "eyeOff" : "eye"} color={ui.mutedForeground} />
      </Pressable>
    </View>
  );
}
