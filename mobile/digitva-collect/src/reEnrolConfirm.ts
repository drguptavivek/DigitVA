/**
 * Change server = re-enrol. Re-enrolling signs every interviewer out of this
 * phone (each sign-out keeps that interviewer's encrypted store, src/auth.ts
 * signOut, but a profile is shown only on its own server) and drops the
 * enrolment (forgetDevice), so it is refused while a signed-in interviewer
 * has anything unsent: drafts, registrations, queued case actions, revisions
 * (countUnsentWork). A signed-in interviewer's locked store cannot be counted
 * and refuses too, the same "maybe unsent" rule as session_revoked. A
 * signed-out profile's store is always locked and cannot be opened without
 * signing in, so it does not refuse (owner decision 2026-10-27): the
 * confirmation names it and says its data stays here, encrypted, and can be
 * sent only from this server.
 */
import { Alert } from "react-native";

import { forgetDevice, signOut, type Account } from "./auth";
import { t } from "./i18n";
import { unsentWorkCount } from "./interviewerDb";

/**
 * `blocked`: one line per interviewer whose store holds, or may hold, unsent
 * work; re-enrolling waits for these. `kept`: the names of signed-out profiles
 * whose locked store is kept as it is. Both empty when re-enrolling loses nothing.
 */
async function unsentReasons(accounts: Account[]): Promise<{ blocked: string[]; kept: string[] }> {
  const counts = await Promise.all(accounts.map((account) => unsentWorkCount(account.user_id)));
  const blocked: string[] = [];
  const kept: string[] = [];
  accounts.forEach((account, index) => {
    const count = counts[index];
    if (count === 0) return;
    if (count === undefined && account.signed_out) kept.push(account.name);
    else blocked.push(count === undefined ? t("reEnrolLockedName", { name: account.name }) : t("reEnrolUnsentName", { name: account.name, count }));
  });
  return { blocked, kept };
}

/**
 * Sign every interviewer out (each signOut tells the enrolled server first),
 * then drop the enrolment. Counts again first, since work may have been saved
 * after the confirmation opened, and throws `unsent_work` on the same rule as
 * the confirmation: kept work could be sent only from this server. Then `lock`
 * (AppState lockNow) saves open work and closes the stores, which sign-out keeps.
 */
export async function reEnrolDevice(accounts: Account[], lock: () => Promise<boolean>): Promise<void> {
  if ((await unsentReasons(accounts)).blocked.length) throw new Error("unsent_work");
  if (!(await lock())) throw new Error("lock_failed");
  for (const account of accounts) await signOut(account.user_id);
  await forgetDevice();
}

/** Refuse with the reason per interviewer, or ask once (naming kept signed-out profiles) and call `onConfirmed`. */
export async function confirmReEnrol(accounts: Account[], onConfirmed: () => void): Promise<void> {
  const { blocked, kept } = await unsentReasons(accounts);
  if (blocked.length) {
    Alert.alert(t("reEnrol"), `${t("reEnrolBlocked")}\n\n${blocked.join("\n")}`, [{ text: t("reEnrolClose") }]);
    return;
  }
  const message = kept.length
    ? `${t("reEnrolConfirm")}\n\n${t("reEnrolKeptSignedOut", { list: kept.join("\n") })}`
    : t("reEnrolConfirm");
  Alert.alert(t("reEnrol"), message, [
    { text: t("cancel"), style: "cancel" },
    {
      text: t("reEnrol"),
      style: "destructive",
      onPress: onConfirmed,
    },
  ]);
}
