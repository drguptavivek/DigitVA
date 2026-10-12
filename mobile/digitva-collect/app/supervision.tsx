import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { SupervisionScreen } from "../src/browserScreens";

export default function SupervisionRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <SupervisionScreen />;
}
