import { Platform } from "react-native";
import { Redirect } from "expo-router";

import DataScreen from "../src/web/DataScreen";

export default function DataRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <DataScreen />;
}
