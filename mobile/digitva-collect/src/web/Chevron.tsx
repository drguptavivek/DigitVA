import { useState } from "react";
import { Pressable, View, type PressableProps } from "react-native";
import Svg, { Path } from "react-native-svg";

import { useTheme } from "../theme";

/** Tabler chevron-down/right/left/up: one path per direction, so no transform (DORIS cards forbid one, digitva-4x2y). */
const PATHS = { down: "M6 9l6 6l6 -6", right: "M9 6l6 6l-6 6", left: "M15 6l-6 6l6 6", up: "M6 15l6 -6l6 6" } as const;

/**
 * Tabler "chevron-down", 22px in the text colour by default: points down when open, right when closed.
 * `direction` overrides that for back arrows and the like; `size` and `color` fit it into tighter spots.
 */
export function Chevron({ expanded, direction, size = 22, color }: { expanded: boolean; direction?: keyof typeof PATHS; size?: number; color?: string }) {
  const { ui } = useTheme();
  return (
    <View aria-hidden>
      <Svg width={size} height={size} viewBox="0 0 24 24">
        <Path d={PATHS[direction ?? (expanded ? "down" : "right")]} stroke={color ?? ui.foreground} strokeWidth={2.5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </View>
  );
}

/** A fold/unfold button: role, expanded state and label for assistive tech, and a focus ring (web outline) for the keyboard. */
export function FoldButton({ label, expanded, style, ...rest }: PressableProps & { label: string; expanded: boolean }) {
  const { ui } = useTheme();
  const [focused, setFocused] = useState(false);
  const ring = focused ? ({ outlineWidth: 2, outlineStyle: "solid", outlineColor: ui.ring } as object) : null;
  return (
    <Pressable
      {...rest}
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ expanded }}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={[style as object, ring]}
    />
  );
}
