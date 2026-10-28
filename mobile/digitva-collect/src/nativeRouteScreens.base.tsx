import { View } from "react-native";

/** Browser fallback for legacy native-only routes. Kept outside platform resolution. */
function BrowserNativeRoute() {
  return <View />;
}

export const Case = BrowserNativeRoute;
export const Demo = BrowserNativeRoute;
export const Enrol = BrowserNativeRoute;
export const Form = BrowserNativeRoute;
export const Home = BrowserNativeRoute;
export const PinSetup = BrowserNativeRoute;
export const Register = BrowserNativeRoute;
export const SignIn = BrowserNativeRoute;
export const Unlock = BrowserNativeRoute;
export const Standalone = BrowserNativeRoute;
export const StandaloneSetup = BrowserNativeRoute;
export const Worklist = BrowserNativeRoute;
export const Revision = BrowserNativeRoute;
export const Settings = BrowserNativeRoute;
export const ProfileAccess = BrowserNativeRoute;
export const OpenSourceLicenses = BrowserNativeRoute;
export const Coding = BrowserNativeRoute;
export const Reviewing = BrowserNativeRoute;
export const Workspace = BrowserNativeRoute;
