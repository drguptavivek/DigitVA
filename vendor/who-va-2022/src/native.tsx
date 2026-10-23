/**
 * React Native package entry point, binding shared form and question-control
 * factories to native primitives while re-exporting the headless API.
 */
import React, { useState } from "react";
import {
  AccessibilityInfo,
  findNodeHandle,
  Image,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  useColorScheme,
  View
} from "react-native";
import Svg, { Circle as SvgCircle, Path as SvgPath } from "react-native-svg";

import { createWhoVaForm } from "./ui/create-who-va-form.js";
import { createWhoVaQuestionControls } from "./ui/question-controls.js";
import { loadWhoVa2022Instrument } from "./instrument-loader.js";

interface NativeSelectProps {
  accessibilityLabel?: string;
  disabled?: boolean;
  emptyOptionLabel?: string;
  onValueChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string }>;
  style?: unknown;
  testID?: string;
  /** A box above the list for typing a value that is in `options` (a year). */
  typedEntry?: boolean;
  value: string;
}

/** A dependency-free select primitive used by shared date selectors on native. */
const NativeSelect = React.forwardRef<unknown, NativeSelectProps>(function NativeSelect(
  { accessibilityLabel, disabled, emptyOptionLabel, onValueChange, options, style, testID, typedEntry, value },
  _ref
) {
  const [open, setOpen] = useState(false);
  const colorScheme = useColorScheme();
  const darkMode = colorScheme === "dark";
  const selectableOptions = [
    { value: "", label: emptyOptionLabel ?? "" },
    ...options.filter((option) => option.value !== "")
  ];
  const selected = selectableOptions.find((option) => option.value === value)?.label ?? "";
  return (
    <View style={style as never}>
      <Pressable
        accessibilityLabel={accessibilityLabel}
        accessibilityRole="button"
        accessibilityState={{ disabled: disabled || undefined, expanded: open }}
        disabled={disabled}
        onPress={() => setOpen((current) => !current)}
        // The wrapper's style draws the bordered field; the slop makes its padding tappable too.
        hitSlop={{ top: 9, bottom: 9, left: 12, right: 12 }}
        style={{ alignItems: "center", flexDirection: "row", justifyContent: "space-between", minHeight: 26 }}
        testID={testID}
      >
        <Text
          numberOfLines={1}
          style={{ color: selected ? (darkMode ? "#f9fafb" : "#142a24") : darkMode ? "#9ca3af" : "#667085", flexShrink: 1, fontSize: 16 }}
        >
          {selected || emptyOptionLabel || ""}
        </Text>
        <Text aria-hidden style={{ color: darkMode ? "#d1d5db" : "#475467", fontSize: 14, marginLeft: 8 }}>
          ▾
        </Text>
      </Pressable>
      {open ? (
        <Modal transparent animationType="fade" visible onRequestClose={() => setOpen(false)}>
          <View accessibilityViewIsModal style={{ flex: 1, alignItems: "center", justifyContent: "center" }}>
            <Pressable
              accessibilityLabel="Close options"
              accessibilityRole="button"
              onPress={() => setOpen(false)}
              style={{
                position: "absolute",
                top: 0,
                right: 0,
                bottom: 0,
                left: 0,
                backgroundColor: "rgba(0, 0, 0, 0.45)"
              }}
              testID={testID ? `${testID}-backdrop` : undefined}
            />
            <View
              style={{
                width: "90%",
                maxWidth: 420,
                maxHeight: "80%",
                overflow: "hidden",
                borderRadius: 12,
                borderWidth: 1,
                borderColor: darkMode ? "#4b5563" : "#cbd5e1",
                backgroundColor: darkMode ? "#1f2937" : "#ffffff",
                shadowColor: "#000000",
                shadowOpacity: 0.2,
                shadowRadius: 12,
                shadowOffset: { width: 0, height: 4 },
                elevation: 6
              }}
              testID={testID ? `${testID}-surface` : undefined}
            >
              {typedEntry ? (
                <TextInput
                  accessibilityLabel={accessibilityLabel}
                  autoCorrect={false}
                  keyboardType="number-pad"
                  maxLength={4}
                  onChangeText={(text: string) => {
                    // A whole four-digit year the list offers is chosen at once; anything else is ignored.
                    if (/^\d{4}$/.test(text) && options.some((option) => option.value === text)) {
                      onValueChange(text);
                      setOpen(false);
                    }
                  }}
                  placeholder="YYYY"
                  placeholderTextColor={darkMode ? "#9ca3af" : "#667085"}
                  style={{
                    borderBottomColor: darkMode ? "#4b5563" : "#cbd5e1",
                    borderBottomWidth: 1,
                    color: darkMode ? "#f9fafb" : "#111827",
                    fontSize: 16,
                    minHeight: 48,
                    paddingHorizontal: 20
                  }}
                  testID={testID ? `${testID}-typed` : undefined}
                />
              ) : null}
              <ScrollView showsVerticalScrollIndicator testID={testID ? `${testID}-options` : undefined}>
                {selectableOptions.map((option) => {
                  const selectedOption = option.value === value;
                  return (
                    <Pressable
                      accessibilityRole="button"
                      accessibilityState={{ selected: selectedOption }}
                      disabled={disabled}
                      key={option.value}
                      onPress={() => {
                        if (disabled) return;
                        onValueChange(option.value);
                        setOpen(false);
                      }}
                      style={{
                        minHeight: 48,
                        paddingHorizontal: 20,
                        paddingVertical: 12,
                        justifyContent: "center",
                        backgroundColor: selectedOption ? (darkMode ? "#374151" : "#e6f1f6") : "transparent"
                      }}
                      testID={testID ? `${testID}-option-${option.value || "empty"}` : undefined}
                    >
                      <Text style={{ color: darkMode ? "#f9fafb" : "#111827", fontSize: 16 }}>
                        {option.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </ScrollView>
            </View>
          </View>
        </Modal>
      ) : null}
    </View>
  );
});

/**
 * Scroll a question to the top of the form's ScrollView. The row's own `y` is
 * relative to its card, so measure against the scroll content instead and
 * fall back to `y` when measuring is not possible.
 */
function scrollToNativeQuestion(questionNode: unknown, scrollViewNode: unknown, y: number): void {
  const scroll = scrollViewNode as {
    scrollTo?: (options: { animated: boolean; y: number }) => void;
    getInnerViewRef?: () => unknown;
    getInnerViewNode?: () => unknown;
  } | null;
  if (!scroll?.scrollTo) return;
  const fallback = () => scroll.scrollTo?.({ y: Math.max(0, y - 12), animated: true });
  const question = questionNode as {
    measureLayout?: (relativeTo: unknown, onSuccess: (x: number, y: number) => void, onFail: () => void) => void;
  } | null;
  const inner = scroll.getInnerViewRef?.() ?? scroll.getInnerViewNode?.();
  if (!question?.measureLayout || !inner) return fallback();
  try {
    question.measureLayout(inner, (_x, top) => scroll.scrollTo?.({ y: Math.max(0, top - 12), animated: true }), fallback);
  } catch {
    fallback();
  }
}

/** Move TalkBack / VoiceOver focus to a node (the section title, a question). */
function focusNativeNode(node: unknown): void {
  try {
    const handle = findNodeHandle(node as never);
    if (handle != null) AccessibilityInfo.setAccessibilityFocus(handle);
  } catch {
    // Focus is a courtesy; the scroll already happened.
  }
}

export * from "./core.js";
export {
  WHO_VA_2022_LANGUAGES,
  loadWhoVa2022Instrument,
  loadWhoVa2022Language
} from "./instrument-loader.js";
export { processNativeImageAttachment } from "./native-attachments.js";
export type * from "./native-attachments.js";
export type { WhoVaDraftController, WhoVaFormProps, WhoVaPlatformServices } from "./ui/create-who-va-form.js";

export const WhoVaForm = createWhoVaForm(
  {
    View,
    Text,
    TextInput,
    Pressable,
    ScrollView,
    Image,
    Modal,
    Svg,
    SvgCircle,
    SvgPath,
    PartialSelect: NativeSelect,
    scrollToQuestion: scrollToNativeQuestion,
    focusNode: focusNativeNode
  },
  loadWhoVa2022Instrument
);
export const WhoVaQuestionControls = createWhoVaQuestionControls({
  View,
  Text,
  TextInput,
  Pressable,
  Image,
  PartialSelect: NativeSelect
});
export type { WhoVaQuestionControlProps } from "./ui/question-controls.js";
