/**
 * React Native package entry point, binding shared form and question-control
 * factories to native primitives while re-exporting the headless API.
 */
import React, { useState } from "react";
import { Image, Modal, Pressable, ScrollView, Text, TextInput, useColorScheme, View } from "react-native";
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
  value: string;
}

/** A dependency-free select primitive used by shared date selectors on native. */
const NativeSelect = React.forwardRef<unknown, NativeSelectProps>(function NativeSelect(
  { accessibilityLabel, disabled, emptyOptionLabel, onValueChange, options, style, testID, value },
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
        testID={testID}
      >
        <Text>{selected}</Text>
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
    PartialSelect: NativeSelect
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
