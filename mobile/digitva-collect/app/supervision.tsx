import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { Supervision } from "../src/nativeRouteScreens";

/**
 * Browser: supervisors work in the Deaths tab (docs/policy/case-list-views.md, "Supervision preset"); old links land there.
 * Phone: the supervision screen (src/nativeRoutes/supervision.tsx).
 */
export default function SupervisionRoute() {
  if (Platform.OS !== "web") return <Supervision />;
  return <Redirect href={{ pathname: "/death-registration", params: { view: "mine", preset: "supervision" } }} />;
}
