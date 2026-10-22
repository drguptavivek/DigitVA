import { Platform } from "react-native";
import { Redirect } from "expo-router";

import UsersScreen from "../src/web/UsersScreen";

export default function UsersRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <UsersScreen />;
}
