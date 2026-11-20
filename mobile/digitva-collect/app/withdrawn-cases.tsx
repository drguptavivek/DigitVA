import { Platform } from "react-native";
import { Redirect } from "expo-router";

import WithdrawnCasesScreen from "../src/web/WithdrawnCasesScreen";

export default function WithdrawnCasesRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <WithdrawnCasesScreen />;
}
