/** Accounts home: interviewers signed in on this device, by display name and lock state only. */
import { Redirect, useRouter } from "expo-router";
import { ActivityIndicator, Platform, Pressable, Text, View } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { isUnlocked } from "../interviewerDb";
import { Button, Screen, useUiStyles } from "../ui";
import { WorkspaceScreen } from "../browserScreens";

export default function Home() {
  const styles = useUiStyles();
  if (Platform.OS === "web") return <WorkspaceScreen />;
  const router = useRouter();
  // The context value changes on every lock and unlock, so this re-renders.
  const { ready, device, accounts } = useAppState();
  if (!ready) return <ActivityIndicator style={{ flex: 1 }} />;
  if (!device) return <Redirect href="/enrol" />;
  return (
    <Screen title={t("accountsTitle")}>
      <Text style={styles.muted}>{device.project_name}</Text>
      {accounts.length === 0 ? <Text style={styles.text}>{t("accountsEmpty")}</Text> : null}
      {accounts.map((account) => (
        <Pressable
          key={account.user_id}
          accessibilityRole="button"
          style={styles.card}
          onPress={() =>
            router.push({
              pathname: isUnlocked(account.user_id) ? "/worklist" : "/unlock",
              params: { userId: account.user_id }
            })
          }
        >
          <Text style={styles.text}>{account.name}</Text>
          <Text style={styles.muted}>
            {isUnlocked(account.user_id) ? t("unlockedState") : t("locked")}
          </Text>
          {account.needs_sign_in ? <Text style={styles.muted}>{t("signInAgain")}</Text> : null}
        </Pressable>
      ))}
      <View style={{ gap: 8 }}>
        <Button label={t("addInterviewer")} onPress={() => router.push("/sign-in")} />
        <Button kind="secondary" label={t("settings")} onPress={() => router.push("/settings")} />
      </View>
    </Screen>
  );
}
