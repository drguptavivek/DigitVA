import { Redirect, useLocalSearchParams } from "expo-router";
import { Platform } from "react-native";

export default function TrainingReviewRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  const params = useLocalSearchParams();
  return <Redirect href={{ pathname: "/training/reviewing", params } as never} />;
}
