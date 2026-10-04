import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { InterviewScreen } from "../src/browserScreens";

export default function InterviewRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <InterviewScreen />;
}
