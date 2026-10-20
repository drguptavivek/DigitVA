import { useState } from "react";
import { Pressable, View, type PressableProps } from "react-native";
import Svg, { Path } from "react-native-svg";

import { useTheme } from "../theme";

/** Tabler "chevron-down" at 22px in the text colour: points down when open, right when closed. */
export function Chevron({ expanded }: { expanded: boolean }) {
  const { ui } = useTheme();
  return (
    <View style={{ transform: [{ rotate: expanded ? "0deg" : "-90deg" }] }} aria-hidden>
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M6 9l6 6l6 -6" stroke={ui.foreground} strokeWidth={2.5} fill="none" strokeLinecap="round" strokeLinejoin="round" />
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
