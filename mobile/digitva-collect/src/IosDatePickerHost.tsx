/**
 * Shows the date picker that platformServices.pickDate asks for on iOS (src/iosDatePicker.ts), in a modal with
 * Cancel and Done. Mounted once by the native shell (src/nativeShell/chrome.tsx); renders nothing on Android,
 * where the system dialog is used, and while no date is asked for.
 */
import { useEffect, useState } from "react";
import { Modal, Platform, StyleSheet, Text, View } from "react-native";

import { t } from "./i18n";
import { type DateRequest, finishIosDate, subscribeIosDate } from "./iosDatePicker";
import { controls, radius, spacing, useTheme } from "./theme";
import { Button } from "./ui";

export function IosDatePickerHost() {
  const [request, setRequest] = useState<DateRequest>();
  const [value, setValue] = useState<Date>(new Date());
  const { colors, typography } = useTheme();

  useEffect(() => {
    if (Platform.OS !== "ios") return undefined;
    return subscribeIosDate((next) => {
      setRequest(next);
      if (next) setValue(next.initial);
    });
  }, []);

  if (Platform.OS !== "ios" || !request) return null;
  // Loaded on first use, as in src/workspace/doris/DateField.native.tsx.
  const Picker = (require("@react-native-community/datetimepicker") as typeof import("@react-native-community/datetimepicker")).default;
  const cancel = () => finishIosDate(request.id, undefined);
  return (
    <Modal visible transparent animationType="fade" onRequestClose={cancel}>
      <View style={s.backdrop}>
        <View accessibilityViewIsModal accessibilityLabel={t("datePickerTitle")}
          style={[s.dialog, { backgroundColor: colors.surface, borderColor: colors.border }]}>
          <Text accessibilityRole="header" style={[s.title, typography.headline, { color: colors.text }]}>{t("datePickerTitle")}</Text>
          <Picker testID="ios-date-picker" value={value} mode="date" display="inline"
            onChange={(_event, date) => { if (date) setValue(date); }} />
          <View style={s.actions}>
            <Button kind="secondary" label={t("cancel")} onPress={cancel} />
            <Button label={t("datePickerDone")} onPress={() => finishIosDate(request.id, value)} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

const s = StyleSheet.create({
  backdrop: { flex: 1, alignItems: "center", justifyContent: "center", padding: spacing.md, backgroundColor: "rgba(0,0,0,0.5)" },
  dialog: { width: "100%", maxWidth: 420, borderWidth: 1, borderRadius: radius.lg, padding: spacing.md, gap: spacing.sm },
  title: { fontFamily: controls.fontFamily },
  actions: { flexDirection: "row", justifyContent: "flex-end", flexWrap: "wrap", gap: spacing.xs },
});
