import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import OfflineProfileScreen from "../src/nativeRoutes/offlineProfile";

/** Collect Plus only (Android); any other build or the web goes home. */
export default function OfflineProfileRoute() {
  return Platform.OS === "android" && isPlusVariant() ? <OfflineProfileScreen /> : <Redirect href="/" />;
}
