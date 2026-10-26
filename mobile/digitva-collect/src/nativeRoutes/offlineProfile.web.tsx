/**
 * Web twin of the Collect Plus offline profile screen (offlineProfile.native.tsx): the profile lives only on the
 * Android Collect Plus build, so this route only ever redirects home and must not pull SecureStore into the web
 * bundle.
 */
import { Redirect } from "expo-router";

export default function OfflineProfileWeb() {
  return <Redirect href="/" />;
}
