import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingReviewScreen } from "../../../src/web/WorkspaceScreen";
import { TrainingScope } from "../../../src/AppState";

export default function TrainingReviewingCaseRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingScope><TrainingReviewScreen /></TrainingScope>;
}
