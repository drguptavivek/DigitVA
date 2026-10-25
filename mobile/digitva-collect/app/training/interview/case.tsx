import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingInterviewCaseScreen } from "../../../src/web/TrainingScreen";

export default function TrainingInterviewCaseRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingInterviewCaseScreen />;
}
