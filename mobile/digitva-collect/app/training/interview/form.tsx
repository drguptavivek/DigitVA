import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingInterviewFormScreen } from "../../../src/web/TrainingScreen";

export default function TrainingInterviewFormRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingInterviewFormScreen />;
}
