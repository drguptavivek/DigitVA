import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import { offlineEnginePlatform } from "../src/platformFamily";
import OfflineProfileScreen from "../src/nativeRoutes/offlineProfile";

/** Collect Plus only (Android or iOS); any other build or the web goes home. */
export default function OfflineProfileRoute() {
  return offlineEnginePlatform() && isPlusVariant() ? <OfflineProfileScreen /> : <Redirect href="/" />;
}
