import { useRouter } from "expo-router";
import { Text } from "react-native";

import { t } from "./i18n";
import { Button, Screen, useUiStyles } from "./ui";

export { default as Case } from "./nativeRoutes/case";
export { default as Demo } from "./nativeRoutes/demo";
export { default as Enrol } from "./nativeRoutes/enrol";
export { default as Form } from "./nativeRoutes/form";
export { default as Home } from "./nativeRoutes/index";
export { default as PinSetup } from "./nativeRoutes/pin-setup";
export { default as Register } from "./nativeRoutes/register";
export { default as SignIn } from "./nativeRoutes/sign-in";
export { default as Unlock } from "./nativeRoutes/unlock";
export { default as Worklist } from "./nativeRoutes/worklist";
export { default as Revision } from "./nativeRoutes/revision";
export { default as Settings } from "./nativeRoutes/settings";

/**
 * The Android app collects data only (docs/policy/field-data-collection.md).
 * Coding, review and the case workspace stay in the web app, so an old link
 * or a coder-only account lands here instead of on a coding screen.
 */
export function CodingOnWeb() {
  const router = useRouter();
  const styles = useUiStyles();
  return <Screen title={t("workspaceTitle")}>
    <Text accessibilityRole="alert" style={styles.text}>{t("codingOnWeb")}</Text>
    <Button kind="secondary" label={t("home")} onPress={() => router.replace("/")} />
  </Screen>;
}

export { CodingOnWeb as Coding, CodingOnWeb as Reviewing, CodingOnWeb as Workspace };
