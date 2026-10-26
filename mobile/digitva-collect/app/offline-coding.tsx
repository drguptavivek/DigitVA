import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import OfflineCoding from "../src/nativeRoutes/offlineCoding";

/** Collect Plus only (Android); any other build or the web goes home. */
export default function OfflineCodingRoute() {
  return Platform.OS === "android" && isPlusVariant() ? <OfflineCoding /> : <Redirect href="/" />;
}
