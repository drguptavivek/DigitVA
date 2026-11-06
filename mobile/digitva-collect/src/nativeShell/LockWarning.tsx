/**
 * The auto-lock warning (WCAG 2.2.1, src/autoLock.ts): 30 seconds before the idle lock, a non-modal notice under
 * the header says so and offers "Stay unlocked", which restarts the timer (any touch does too). The notice is
 * announced (a warning Notice is an assertive live region, and VoiceOver hears it through `announce`).
 */
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useAppState } from "../AppState";
import { LOCK_WARNING_MS } from "../autoLock";
import { t } from "../i18n";
import { spacing } from "../theme";
import { Notice, TextLink } from "../ui";
import { useShell } from "./shellContext";

export function LockWarning() {
  const { lockWarning, activity } = useAppState();
  const { header } = useShell();
  const insets = useSafeAreaInsets();
  if (!lockWarning) return null;
  return (
    // Without the phone header (the forms) the notice clears the status bar itself.
    <View style={{ paddingHorizontal: spacing.md, paddingTop: (header ? 0 : insets.top) + spacing.xs }}>
      <Notice tone="warning" testID="lock-warning" action={<TextLink label={t("lockWarningStay")} onPress={activity} />}>
        {t("lockWarningText", { seconds: LOCK_WARNING_MS / 1000 })}
      </Notice>
    </View>
  );
}
