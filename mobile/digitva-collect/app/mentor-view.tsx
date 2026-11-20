import { Platform } from "react-native";
import { Redirect } from "expo-router";

import MentorViewScreen from "../src/web/MentorViewScreen";

export default function MentorViewRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <MentorViewScreen />;
}
