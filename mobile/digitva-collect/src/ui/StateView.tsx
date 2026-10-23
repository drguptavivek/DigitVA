/**
 * The three list states of the phone app (Empty, Loading, Offline), shared by Home, Interviews and Registered
 * deaths. Loading is skeleton card rows, never a bare spinner; Offline is a persistent notice, not a toast.
 */
import { Text, View } from "react-native";
import Svg, { Path } from "react-native-svg";

import { t } from "../i18n";
import { radius, spacing, typography, useTheme } from "../theme";
import { Button } from "../ui";

const ICONS = {
  empty: ["M9 6l11 0", "M9 12l11 0", "M9 18l11 0", "M5 6l0 .01", "M5 12l0 .01", "M5 18l0 .01"],
  offline: ["M12 18l.01 0", "M9.2 15.1a4 4 0 0 1 5.6 0", "M6.4 12.3a8 8 0 0 1 11.2 0", "M3 3l18 18"],
  error: ["M12 9v4", "M12 16v.01", "M10.3 3.9l-8.5 14.5a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7 -3l-8.5 -14.5a2 2 0 0 0 -3.4 0"],
} as const;

export function StateIcon({ name, color, size = 24 }: { name: keyof typeof ICONS; color: string; size?: number }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {ICONS[name].map((d) => <Path key={d} d={d} />)}
    </Svg>
  );
}

/** Empty or failed list: icon, title, hint and at most one action. */
export function StateView({ kind = "empty", title, hint, actionLabel, onAction }: { kind?: "empty" | "error"; title: string; hint?: string; actionLabel?: string; onAction?: () => void }) {
  const { ui } = useTheme();
  return (
    <View testID={`state-${kind}`} accessibilityRole={kind === "error" ? "alert" : undefined} style={{ alignItems: "center", gap: spacing.xs, paddingVertical: spacing.lg, paddingHorizontal: spacing.md }}>
      <StateIcon name={kind} color={kind === "error" ? ui.destructiveText : ui.mutedForeground} size={32} />
      <Text accessibilityRole="header" style={{ ...typography.headline, color: ui.foreground, textAlign: "center" }}>{title}</Text>
      {hint ? <Text style={{ ...typography.body, color: ui.mutedForeground, textAlign: "center" }}>{hint}</Text> : null}
      {actionLabel && onAction ? <Button label={actionLabel} onPress={onAction} /> : null}
    </View>
  );
}

/** Placeholder card rows while the local store is read; hidden from screen readers except one "Loading" label. */
export function SkeletonCards({ count = 3 }: { count?: number }) {
  const { ui } = useTheme();
  const bar = (width: string, height = 14) => <View style={{ width: width as `${number}%`, height, borderRadius: 4, backgroundColor: ui.border }} />;
  return (
    <View testID="state-loading" accessible accessibilityLabel={t("loading")} accessibilityState={{ busy: true }} style={{ gap: spacing.xs }}>
      {Array.from({ length: count }, (_, index) => (
        <View key={index} importantForAccessibility="no-hide-descendants" style={{ gap: spacing.xs, padding: spacing.sm, borderRadius: radius.lg, borderWidth: 1, borderColor: ui.border, backgroundColor: ui.card }}>
          {bar("55%", 18)}
          {bar("35%")}
          {bar("80%")}
        </View>
      ))}
    </View>
  );
}

/** Persistent "offline" banner. Work is safe on the phone; only network actions wait. */
export function OfflineNotice() {
  const { ui } = useTheme();
  return (
    <View testID="state-offline" accessibilityRole="alert" style={{ flexDirection: "row", gap: spacing.xs, padding: spacing.sm, borderRadius: radius.md, borderWidth: 1, borderColor: ui.warningBorder, backgroundColor: ui.warning }}>
      <StateIcon name="offline" color={ui.warningForeground} size={20} />
      <Text style={{ ...typography.subhead, color: ui.warningForeground, flex: 1 }}>{t("offlineNotice")}</Text>
    </View>
  );
}
