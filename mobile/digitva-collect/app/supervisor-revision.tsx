import { Redirect } from "expo-router";
import { Platform } from "react-native";

import { SupervisorRevision } from "../src/nativeRouteScreens";

/** Phone only: a supervisor's interview correction. The browser edits it in the interview screen (`revisionBy=supervisor`). */
export default function SupervisorRevisionRoute() {
  if (Platform.OS !== "web") return <SupervisorRevision />;
  return <Redirect href="/supervision" />;
}
