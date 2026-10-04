import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { DeathRegistrationScreen } from "../src/browserScreens";

export default function DeathRegistrationRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <DeathRegistrationScreen />;
}
