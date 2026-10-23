import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingInterviewScreen } from "../../src/web/TrainingScreen";

export default function TrainingInterviewRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingInterviewScreen />;
}
