import { useLayoutEffect, useRef, useState } from "react";
import { Platform, TextInput } from "react-native";

import { spacing, useTheme } from "./theme";
import { useUiStyles } from "./ui";

const CHROME = spacing.xs * 2 + 4; // input vertical padding plus the 2px focus edge top and bottom

/** Two to six body lines of the current Text size, plus the field's padding and edge. */
const clampTo = (line: number) => (height: number) => Math.min(line * 6 + CHROME, Math.max(line * 2 + CHROME, height));

/**
 * A plain multiline field for registration Address and Remarks: the same look
 * as the single-line inputs, two lines tall when empty, growing with its text
 * up to six lines and scrolling beyond that.
 */
export function MultilineInput({ label, value, onChange, disabled, edge = false }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  /** Inside a white card: the faint hairline edge (styles.inputHairline). */
  edge?: boolean;
}) {
  const styles = useUiStyles();
  const { typography } = useTheme();
  const clamp = clampTo(typography.body.lineHeight);
  const ref = useRef<TextInput>(null);
  const [height, setHeight] = useState(clamp(0));
  // Only the focused field draws its ring (docs/policy/expo-client.md "Theme").
  const [focused, setFocused] = useState(false);
  // react-native-web reports the box size, not the content size, so measure the textarea itself.
  useLayoutEffect(() => {
    if (Platform.OS !== "web") return;
    const el = ref.current as unknown as HTMLTextAreaElement | null;
    if (!el?.style) return;
    el.style.height = "auto";
    const next = clamp(el.scrollHeight + 2);
    el.style.height = `${next}px`; // React skips the re-render when the state is unchanged
    setHeight(next);
  }, [value]);
  return (
    <TextInput
      ref={ref}
      accessibilityLabel={label}
      multiline
      editable={!disabled}
      value={value}
      onChangeText={onChange}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      onContentSizeChange={Platform.OS === "web" ? undefined : (event) => setHeight(clamp(event.nativeEvent.contentSize.height + CHROME))}
      style={[styles.input, edge && styles.inputHairline, focused && styles.inputFocused, { height, textAlignVertical: "top" }]}
    />
  );
}
