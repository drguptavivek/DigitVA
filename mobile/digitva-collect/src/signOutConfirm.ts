/**
 * The one native sign-out confirmation. Sign-out wipes the interviewer's
 * store, so while anything is unsent it is refused and says what, kind by
 * kind (Home shows only interview drafts). A locked store cannot be counted
 * (or read without the PIN), so it warns and asks a second time instead.
 */
import { Alert } from "react-native";

import { t } from "./i18n";
import { unsentWorkKinds } from "./interviewerDb";

const KIND_LABELS = [
  ["interviews", "unsentKindInterviews"],
  ["registrations", "unsentKindRegistrations"],
  ["actions", "unsentKindActions"],
  ["revisions", "unsentKindRevisions"],
] as const;

export async function confirmSignOut(userId: string, onConfirmed: () => void): Promise<void> {
  const kinds = await unsentWorkKinds(userId);
  const cancel = { text: t("cancel"), style: "cancel" as const };
  if (!kinds) {
    Alert.alert(t("signOut"), t("signOutUnknownUnsent"), [
      cancel,
      {
        text: t("signOutConfirm"),
        style: "destructive",
        onPress: () =>
          Alert.alert(t("signOutDeletePermanently"), t("pendingSignOutConfirm"), [
            cancel,
            { text: t("signOutDeletePermanently"), style: "destructive", onPress: onConfirmed },
          ]),
      },
    ]);
    return;
  }
  const lines = KIND_LABELS.filter(([kind]) => kinds[kind] > 0).map(([kind, label]) => t(label, { count: kinds[kind] }));
  if (lines.length > 0) {
    Alert.alert(t("signOutBlockedTitle"), t("signOutBlockedUnsent", { list: lines.join("\n") }), [{ text: t("ok") }]);
    return;
  }
  Alert.alert(t("signOut"), t("pendingSignOutConfirm"), [
    cancel,
    { text: t("signOutConfirm"), style: "destructive", onPress: onConfirmed },
  ]);
}
