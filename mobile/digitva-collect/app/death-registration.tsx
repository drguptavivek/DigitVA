import { Redirect, useLocalSearchParams } from "expo-router";
import { Platform } from "react-native";

import { DeathRegistrationScreen } from "../src/browserScreens";
import { hasLegacyTrainingParam } from "../src/training";

export default function DeathRegistrationRoute() {
  const params = useLocalSearchParams();
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  if (hasLegacyTrainingParam(params.training)) return <Redirect href={{ pathname: "/training/reporting", params } as never} />;
  return <DeathRegistrationScreen />;
}
