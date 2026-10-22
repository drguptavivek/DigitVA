/**
 * The one native sign-out confirmation. Sign-out wipes the interviewer's
 * store, so it says how many unsent items will be deleted and, when there
 * are any (or the locked store cannot be counted), asks a second time.
 */
import { Alert } from "react-native";

import { t } from "./i18n";
import { unsentWorkCount } from "./interviewerDb";

export async function confirmSignOut(userId: string, onConfirmed: () => void): Promise<void> {
  const count = await unsentWorkCount(userId);
  const cancel = { text: t("cancel"), style: "cancel" as const };
  if (count === 0) {
    Alert.alert(t("signOut"), t("pendingSignOutConfirm"), [
      cancel,
      { text: t("signOutConfirm"), style: "destructive", onPress: onConfirmed },
    ]);
    return;
  }
  const warning = count === undefined ? t("signOutUnknownUnsent") : t("signOutUnsentCount", { count });
  const final = count === undefined ? t("pendingSignOutConfirm") : t("signOutUnsentFinal", { count });
  Alert.alert(t("signOut"), warning, [
    cancel,
    {
      text: t("signOutConfirm"),
      style: "destructive",
      onPress: () =>
        Alert.alert(t("signOutDeletePermanently"), final, [
          cancel,
          { text: t("signOutDeletePermanently"), style: "destructive", onPress: onConfirmed },
        ]),
    },
  ]);
}
