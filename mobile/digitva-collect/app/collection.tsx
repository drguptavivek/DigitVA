import { Platform } from "react-native";
import { Redirect } from "expo-router";

import { CollectionScreen } from "../src/browserScreens";

export default function CollectionRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <CollectionScreen />;
}
