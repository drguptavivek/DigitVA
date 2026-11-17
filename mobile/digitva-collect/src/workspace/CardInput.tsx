/** A text field on a coding card: the tinted card fill and a theme placeholder colour (dark mode hid it). */
import { TextInput, type TextInputProps } from "react-native";

import { useTheme } from "../theme";
import { useUiStyles } from "../ui";

export function CardInput({ style, ...props }: TextInputProps) {
  const styles = useUiStyles();
  const { ui } = useTheme();
  return <TextInput placeholderTextColor={ui.mutedForeground} {...props} style={[styles.input, styles.inputOnCard, style]} />;
}
