/** The 44px copy and call icons on the phone case cards (Tabler "copy" and "phone"). */
import { Pressable, Share, StyleSheet, View, ActivityIndicator } from "react-native";
import Svg, { Path } from "react-native-svg";

import { radius, useTheme } from "../theme";

const box = StyleSheet.create({ icon: { width: 44, height: 44, alignItems: "center", justifyContent: "center", borderRadius: radius.md } });

// ponytail: QueueScreen's private CopyIcon should switch to this one once the screen-cache branch lands.
/** Shares the card's support text (Copy, WhatsApp, email); a failed or cancelled share is ignored. */
export function CopyIcon({ label, message }: { label: string; message: string }) {
  const { colors } = useTheme();
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={() => void Share.share({ message }).catch(() => undefined)} style={box.icon}>
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M7 9.667a2.667 2.667 0 0 1 2.667 -2.667h8.666a2.667 2.667 0 0 1 2.667 2.667v8.666a2.667 2.667 0 0 1 -2.667 2.667h-8.666a2.667 2.667 0 0 1 -2.667 -2.667z" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        <Path d="M4.012 16.737a2 2 0 0 1 -1.012 -1.737v-10c0 -1.1 .9 -2 2 -2h10c.75 0 1.158 .385 1.5 1" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}

/** Dials the informant; `busy` (a number is being fetched) shows a spinner and ignores taps. */
export function CallIcon({ label, onPress, busy = false }: { label: string; onPress: () => void; busy?: boolean }) {
  const { colors } = useTheme();
  if (busy) return <View style={box.icon}><ActivityIndicator accessibilityLabel={label} /></View>;
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} onPress={onPress} style={box.icon}>
      <Svg width={22} height={22} viewBox="0 0 24 24">
        <Path d="M5 4h4l2 5l-2.5 1.5a11 11 0 0 0 5 5l1.5 -2.5l5 2v4a2 2 0 0 1 -2 2a16 16 0 0 1 -15 -15a2 2 0 0 1 2 -2" stroke={colors.text} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
      </Svg>
    </Pressable>
  );
}
