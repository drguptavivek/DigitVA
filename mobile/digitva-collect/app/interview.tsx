import { Redirect, useLocalSearchParams } from "expo-router";
import { Platform } from "react-native";

import { InterviewScreen } from "../src/browserScreens";
import { hasLegacyTrainingParam } from "../src/training";

export default function InterviewRoute() {
  const params = useLocalSearchParams();
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  if (hasLegacyTrainingParam(params.training)) return <Redirect href={{ pathname: "/training/interview/form", params } as never} />;
  return <InterviewScreen />;
}
