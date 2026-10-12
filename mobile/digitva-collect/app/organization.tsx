import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { OrganizationScreen } from "../src/browserScreens";

export default function OrganizationRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <OrganizationScreen />;
}
