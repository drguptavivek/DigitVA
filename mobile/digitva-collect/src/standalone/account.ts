/**
 * Create the one standalone account of this phone (Path C): Plus on Android only, no network. The account id is
 * derived from the device UUID, and the offline profile is saved first so a failed profile leaves no account. A
 * standalone profile needs every field an interview prefills (standaloneProfileMissing, digitva-0vz7), not only the
 * name and country saveOfflineProfile itself requires. Explicit logout of all server accounts is required before any writes.
 * PIN, store and lock come from the ordinary pin-setup screen afterwards.
 */
import { createStandaloneAccount, standaloneModeAvailable, type Account } from "../auth";
import { getOrCreatePlusDeviceIdentity } from "../offlineIdentity";
import { saveOfflineProfile, standaloneProfileMissing, type OfflineProfile } from "../offlineProfile";
import { standaloneUserId } from "./project";

export async function setUpStandaloneAccount(profile: OfflineProfile): Promise<Account> {
  if (!(await standaloneModeAvailable())) throw new Error("standalone_server_session_active");
  const identity = await getOrCreatePlusDeviceIdentity();
  if (!identity) throw new Error("standalone_plus_only");
  if (standaloneProfileMissing(profile).length) throw new Error("standalone_profile_incomplete");
  await saveOfflineProfile(profile);
  return createStandaloneAccount(standaloneUserId(identity.uuid), profile.name.trim());
}
