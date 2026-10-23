/**
 * Settings: the browser's own screen on the web; on the phone, src/nativeRoutes/settings.tsx (sections for
 * account, language, security, sync, help and about; the enrolled server changes only by re-enrolling).
 */
import { Platform } from "react-native";

import { Settings as NativeSettings } from "../src/nativeRouteScreens";
import { SettingsScreen as WebSettings } from "../src/browserScreens";

export default function Settings() {
  return Platform.OS === "web" ? <WebSettings /> : <NativeSettings />;
}
