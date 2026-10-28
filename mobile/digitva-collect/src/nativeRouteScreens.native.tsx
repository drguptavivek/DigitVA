import { useRouter } from "expo-router";
import { Text } from "react-native";

import { isPlusVariant } from "./appVariant";
import { t } from "./i18n";
import { PlusCoding, PlusReviewing, PlusWorkspace } from "./nativeRoutes/plusWorkspace";
import { Button, Screen, useUiStyles } from "./ui";

export { default as Case } from "./nativeRoutes/case";
export { default as Demo } from "./nativeRoutes/demo";
export { default as Enrol } from "./nativeRoutes/enrol";
export { default as Form } from "./nativeRoutes/form";
export { default as Home } from "./nativeRoutes/index";
export { default as PinSetup } from "./nativeRoutes/pin-setup";
export { default as Register } from "./nativeRoutes/register";
export { default as SignIn } from "./nativeRoutes/sign-in";
export { default as Standalone } from "./nativeRoutes/standalone";
export { default as StandaloneSetup } from "./nativeRoutes/standaloneSetup";
export { default as Unlock } from "./nativeRoutes/unlock";
export { default as Worklist } from "./nativeRoutes/worklist";
export { default as Revision } from "./nativeRoutes/revision";
export { default as Settings } from "./nativeRoutes/settings";
export { default as ProfileAccess } from "./nativeRoutes/profileAccess";
export { default as OpenSourceLicenses } from "./nativeRoutes/openSourceLicenses";

/**
 * The native app shares the server-backed coding workspace in both APK
 * variants. Review remains Plus-only; local ICD-11 tools stay separately
 * gated by the offline capability helper.
 */
export function CodingOnWeb() {
  const router = useRouter();
  const styles = useUiStyles();
  return <Screen title={t("workspaceTitle")}>
    <Text accessibilityRole="alert" style={styles.text}>{t("codingOnWeb")}</Text>
    <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
  </Screen>;
}

// Online coding is the same server-backed workspace in plain and Plus builds.
export const Coding = PlusCoding;
const plus = isPlusVariant();
export const Reviewing = plus ? PlusReviewing : CodingOnWeb;
export const Workspace = PlusWorkspace;
