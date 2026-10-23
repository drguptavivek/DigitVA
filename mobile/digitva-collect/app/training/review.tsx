import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingReviewScreen } from "../../src/web/WorkspaceScreen";

export default function TrainingReviewRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingReviewScreen />;
}
