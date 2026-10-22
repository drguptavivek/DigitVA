import { View } from "react-native";

/** Native route fallbacks. Metro resolves browserScreens.web.tsx for web. */
function NativeWebRoute() {
  return <View />;
}

export const CollectionScreen = NativeWebRoute;
export const DeathRegistrationScreen = NativeWebRoute;
export const InterviewScreen = NativeWebRoute;
export const SettingsScreen = NativeWebRoute;
export const OrganizationScreen = NativeWebRoute;
// The Android app is collection only: /workspace explains that coding is on the web.
export { Workspace as WorkspaceScreen } from "./nativeRouteScreens";
