import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { TrainingRegisterScreen } from "../../src/web/TrainingScreen";

export default function TrainingRegisterRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <TrainingRegisterScreen />;
}
