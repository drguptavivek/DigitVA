import { Platform } from "react-native";

import { TrainingCodingScreen } from "../../../src/web/WorkspaceScreen";
import { TrainingScope } from "../../../src/AppState";
import { TrainingCoding } from "../../../src/nativeRouteScreens";

export default function TrainingCodingCaseRoute() {
  if (Platform.OS !== "web") return <TrainingCoding />;
  return <TrainingScope><TrainingCodingScreen /></TrainingScope>;
}
