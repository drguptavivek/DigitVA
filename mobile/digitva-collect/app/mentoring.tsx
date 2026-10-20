import { Platform } from "react-native";
import { Redirect } from "expo-router";

import MentoringScreen from "../src/web/MentoringScreen";

export default function MentoringRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <MentoringScreen />;
}
