import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import { offlineEnginePlatform } from "../src/platformFamily";
import EngineCheck from "../src/nativeRoutes/engineCheck";

/** Collect Plus only (Android or iOS); any other build or the web goes home. */
export default function EngineCheckRoute() {
  return offlineEnginePlatform() && isPlusVariant() ? <EngineCheck /> : <Redirect href="/" />;
}
