import { View } from "react-native";

/** Native route fallbacks. Metro resolves browserScreens.web.tsx for web. */
function NativeWebRoute() {
  return <View />;
}

export const CollectionScreen = NativeWebRoute;
export const DeathRegistrationScreen = NativeWebRoute;
export const InterviewScreen = NativeWebRoute;
export const SettingsScreen = NativeWebRoute;
export { WorkspaceScreen } from "./nativeRoutes/workspaceScreens";
