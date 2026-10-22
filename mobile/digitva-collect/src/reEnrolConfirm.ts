/**
 * Change server = re-enrol. Re-enrolling signs every interviewer out of this
 * phone (each sign-out wipes that interviewer's store, src/auth.ts signOut)
 * and drops the enrolment (forgetDevice), so it is refused while anything is
 * unsent for anyone: drafts, registrations, queued case actions, revisions
 * (countUnsentWork). A locked store cannot be counted and refuses too, the
 * same "maybe unsent" rule as session_revoked.
 */
import { Alert } from "react-native";

import { forgetDevice, signOut, type Account } from "./auth";
import { t } from "./i18n";
import { unsentWorkCount } from "./interviewerDb";

/** One line per interviewer whose store holds, or may hold, unsent work. Empty when re-enrolling loses nothing. */
async function unsentReasons(accounts: Account[]): Promise<string[]> {
  const counts = await Promise.all(accounts.map((account) => unsentWorkCount(account.user_id)));
  return accounts.flatMap((account, index) => {
    const count = counts[index];
    if (count === 0) return [];
    return [count === undefined ? t("reEnrolLockedName", { name: account.name }) : t("reEnrolUnsentName", { name: account.name, count })];
  });
}

/**
 * Sign every interviewer out (each signOut tells the enrolled server first),
 * then drop the enrolment. Counts again first, since work may have been saved
 * after the confirmation opened; throws `unsent_work` rather than wipe it.
 */
export async function reEnrolDevice(accounts: Account[]): Promise<void> {
  if ((await unsentReasons(accounts)).length) throw new Error("unsent_work");
  for (const account of accounts) await signOut(account.user_id);
  await forgetDevice();
}

/** Refuse with the reason per interviewer, or ask once and call `onConfirmed`. */
export async function confirmReEnrol(accounts: Account[], onConfirmed: () => void): Promise<void> {
  const blocked = await unsentReasons(accounts);
  if (blocked.length) {
    Alert.alert(t("reEnrol"), `${t("reEnrolBlocked")}\n\n${blocked.join("\n")}`, [{ text: t("reEnrolClose") }]);
    return;
  }
  Alert.alert(t("reEnrol"), t("reEnrolConfirm"), [
    { text: t("cancel"), style: "cancel" },
    {
      text: t("reEnrol"),
      style: "destructive",
      onPress: onConfirmed,
    },
  ]);
}
