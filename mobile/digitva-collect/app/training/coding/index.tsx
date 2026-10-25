import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingCodingScreen } from "../../../src/web/WorkspaceScreen";
import { TrainingScope } from "../../../src/AppState";

export default function TrainingCodingRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingScope><TrainingCodingScreen /></TrainingScope>;
}
