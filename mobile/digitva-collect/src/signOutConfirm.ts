/**
 * The one native sign-out confirmation. Sign-out keeps the interviewer's
 * encrypted store (src/auth.ts signOut), so it asks once and says so; work
 * not yet sent is listed by kind (Home shows only interview drafts) and is
 * sent after the interviewer signs in again. A locked store cannot be
 * counted, which loses nothing now, so it asks the same way.
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
  const lines = kinds
    ? KIND_LABELS.filter(([kind]) => kinds[kind] > 0).map(([kind, label]) => t(label, { count: kinds[kind] }))
    : [];
  const message = lines.length > 0
    ? `${t("signOutKeepsData")}\n\n${t("signOutKeptUnsent", { list: lines.join("\n") })}`
    : t("signOutKeepsData");
  Alert.alert(t("signOut"), message, [
    { text: t("cancel"), style: "cancel" },
    { text: t("signOutConfirm"), onPress: onConfirmed },
  ]);
}
