import { Platform } from "react-native";
import { Redirect } from "expo-router";

/** Supervisors work in the Deaths tab (docs/policy/case-list-views.md, "Supervision preset"); old links land there. */
export default function SupervisionRoute() {
  if (Platform.OS !== "web") return <Redirect href="/worklist" />;
  return <Redirect href={{ pathname: "/death-registration", params: { view: "mine", preset: "supervision" } }} />;
}
