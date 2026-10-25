import { Redirect, useLocalSearchParams } from "expo-router";
import { Platform } from "react-native";

export default function TrainingRegisterRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  const params = useLocalSearchParams();
  return <Redirect href={{ pathname: "/training/reporting", params } as never} />;
}
