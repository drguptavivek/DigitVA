import { useLayoutEffect, useRef, useState } from "react";
import { Platform, TextInput } from "react-native";

import { spacing, typography } from "./theme";
import { useUiStyles } from "./ui";

const LINE = typography.body.lineHeight;
const CHROME = spacing.xs * 2 + 2; // input vertical padding plus 1px border top and bottom
const MIN_HEIGHT = LINE * 2 + CHROME;
const MAX_HEIGHT = LINE * 6 + CHROME;

const clamp = (height: number) => Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, height));

/**
 * A plain multiline field for registration Address and Remarks: the same look
 * as the single-line inputs, two lines tall when empty, growing with its text
 * up to six lines and scrolling beyond that.
 */
export function MultilineInput({ label, value, onChange, disabled }: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const styles = useUiStyles();
  const ref = useRef<TextInput>(null);
  const [height, setHeight] = useState(MIN_HEIGHT);
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
      onContentSizeChange={Platform.OS === "web" ? undefined : (event) => setHeight(clamp(event.nativeEvent.contentSize.height + CHROME))}
      style={[styles.input, { height, textAlignVertical: "top" }]}
    />
  );
}
