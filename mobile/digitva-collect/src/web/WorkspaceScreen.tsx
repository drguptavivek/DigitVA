import { useRouter } from "expo-router";
import { Text } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { Button, useUiStyles } from "../ui";
import { WebShell } from "./common";

export default function WorkspaceScreen() {
  const router = useRouter();
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  return (
    <WebShell title={t("workspaceTitle")}>
      {bootstrap ? (
        <>
          <Text style={styles.text}>{t("loginSuccess")}: {bootstrap.user.name}</Text>
          {bootstrap.capabilities.intake ? <Button label={t("navCollection")} onPress={() => router.push("/collection")} /> : null}
        </>
      ) : null}
    </WebShell>
  );
}
