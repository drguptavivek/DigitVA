import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingCodingScreen } from "../../src/web/WorkspaceScreen";

export default function TrainingCodingRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingCodingScreen />;
}
