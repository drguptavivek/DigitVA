import { Platform } from "react-native";
import { Redirect } from "expo-router";

import StatisticsScreen from "../src/web/StatisticsScreen";

export default function StatisticsRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <StatisticsScreen />;
}
