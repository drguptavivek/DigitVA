import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import { offlineEnginePlatform } from "../src/platformFamily";
import OfflineCoding from "../src/nativeRoutes/offlineCoding";

/** Collect Plus only (Android or iOS); any other build or the web goes home. */
export default function OfflineCodingRoute() {
  return offlineEnginePlatform() && isPlusVariant() ? <OfflineCoding /> : <Redirect href="/" />;
}
