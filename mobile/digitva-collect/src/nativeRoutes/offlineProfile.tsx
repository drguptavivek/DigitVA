/**
 * Platform entry for the Collect Plus offline profile route (offlineProfile.native.tsx carries the screen;
 * offlineProfile.web.tsx the web twin): this shared file only ever redirects home and imports nothing
 * native-only, so both bundles can resolve the route path the app directory imports.
 */
import { Redirect } from "expo-router";

export default function OfflineProfileEntry() {
  return <Redirect href="/" />;
}
