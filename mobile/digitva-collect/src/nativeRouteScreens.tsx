import { View } from "react-native";

import { CodingScreen, ReviewingScreen, WorkspaceScreen } from "./nativeRoutes/workspaceScreens";

/** Browser fallback for legacy native-only routes. */
function BrowserNativeRoute() {
  return <View />;
}

export const Case = BrowserNativeRoute;
export const Enrol = BrowserNativeRoute;
export const Form = BrowserNativeRoute;
export const Home = BrowserNativeRoute;
export const PinSetup = BrowserNativeRoute;
export const Register = BrowserNativeRoute;
export const SignIn = BrowserNativeRoute;
export const Unlock = BrowserNativeRoute;
export const Worklist = BrowserNativeRoute;
export const Revision = BrowserNativeRoute;
export const Coding = CodingScreen;
export const Reviewing = ReviewingScreen;
export { WorkspaceScreen as Workspace };
