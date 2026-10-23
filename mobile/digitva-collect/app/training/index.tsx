import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingOverviewScreen } from "../../src/web/TrainingScreen";

export default function TrainingIndexRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingOverviewScreen />;
}
