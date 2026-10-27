/**
 * Create the one standalone account of this phone (Path C): Plus on Android only, no network. The account id is
 * derived from the device UUID, and the offline profile (name and country required) is saved first so a failed
 * profile leaves no account. PIN, store and lock come from the ordinary pin-setup screen afterwards.
 */
import { createStandaloneAccount, type Account } from "../auth";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { saveOfflineProfile, type OfflineProfile } from "../offlineProfile";
import { standaloneUserId } from "./project";

export async function setUpStandaloneAccount(profile: OfflineProfile): Promise<Account> {
  const identity = await getOrCreatePlusDeviceIdentity();
  if (!identity) throw new Error("standalone_plus_only");
  await saveOfflineProfile(profile);
  return createStandaloneAccount(standaloneUserId(identity.uuid), profile.name.trim());
}
