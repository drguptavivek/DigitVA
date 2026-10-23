import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { radius, spacing, typography, useTheme } from "./theme";

export const TOAST_MS = 6_000;
export const TOAST_EXPANDED_MS = 15_000;

/**
 * Transient, non-blocking notice anchored above the bottom inset. The wrapper ignores touches so the page
 * underneath stays usable; only the toast itself takes taps. Tap swaps the short message for `detail` and
 * back. Hides itself via `onHide` after TOAST_MS (TOAST_EXPANDED_MS while expanded); a new `detail` restarts it.
 */
export function Toast({ message, detail, onHide }: { message: string; detail: string; onHide: () => void }) {
  const { ui } = useTheme();
  const insets = useSafeAreaInsets();
  const [expanded, setExpanded] = useState(false);

  useEffect(() => setExpanded(false), [detail]);
  useEffect(() => {
    const timer = setTimeout(onHide, expanded ? TOAST_EXPANDED_MS : TOAST_MS);
    return () => clearTimeout(timer);
  }, [detail, expanded, onHide]);

  return (
    <View
      pointerEvents="box-none"
      style={{ position: "absolute", left: 0, right: 0, bottom: insets.bottom + spacing.md, paddingHorizontal: spacing.md, alignItems: "center" }}
    >
      <Pressable
        accessibilityRole="alert"
        accessibilityLiveRegion="polite"
        focusable={false}
        onPress={() => setExpanded((open) => !open)}
        style={{ maxWidth: 480, width: "100%", backgroundColor: ui.popover, borderColor: ui.border, borderWidth: 1, borderRadius: radius.lg, padding: spacing.sm }}
      >
        <Text
          selectable={expanded}
          numberOfLines={expanded ? undefined : 2}
          style={{ ...typography.subhead, color: ui.popoverForeground }}
        >
          {expanded ? detail : message}
        </Text>
      </Pressable>
    </View>
  );
}
