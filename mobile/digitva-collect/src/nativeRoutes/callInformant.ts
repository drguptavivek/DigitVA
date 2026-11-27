/**
 * Dials a death's informant from a list card. A list row carries only "has a phone", so the number comes from
 * the downloaded case when there is one, else from the case detail (one request). Returns false when no
 * dialable number exists; throws on a failed fetch or dial. The number is never logged or kept.
 */
import { Linking } from "react-native";

import { getNativeRegistrationCase } from "../deathRegistrationApi";
import { deathPhoneUrl } from "../deathWorkflow";

export async function callInformant(userId: string, deathId: string, projectId: string | undefined, localPhone?: string): Promise<boolean> {
  let url = deathPhoneUrl(localPhone);
  if (!url) {
    const { informant } = await getNativeRegistrationCase(userId, deathId, projectId);
    url = deathPhoneUrl(informant.phone) ?? deathPhoneUrl(informant.phone_2);
  }
  if (!url) return false;
  await Linking.openURL(url);
  return true;
}
