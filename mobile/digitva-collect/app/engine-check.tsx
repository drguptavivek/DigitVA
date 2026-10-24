import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { isPlusVariant } from "../src/appVariant";
import EngineCheck from "../src/nativeRoutes/engineCheck";

/** Collect Plus only (Android); any other build or the web goes home. */
export default function EngineCheckRoute() {
  return Platform.OS === "android" && isPlusVariant() ? <EngineCheck /> : <Redirect href="/" />;
}
