import { Redirect } from "expo-router";

import { canTryDorisDemo } from "../src/dorisDemoAccess";
import DorisDemo from "../src/nativeRoutes/dorisDemo";

/** Collect Plus (Android) only, and open without signing in; any other build or the web goes home. */
export default function DorisDemoRoute() {
  return canTryDorisDemo() ? <DorisDemo /> : <Redirect href="/" />;
}
