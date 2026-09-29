/** Accounts home: interviewers signed in on this device, by display name only. */
import { Redirect, useRouter } from "expo-router";
import { ActivityIndicator, Pressable, Text, View } from "react-native";

import { useAppState } from "../src/AppState";
import { t } from "../src/i18n";
import { Button, Screen, styles } from "../src/ui";

export default function Home() {
  const router = useRouter();
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
          onPress={() => router.push({ pathname: "/worklist", params: { userId: account.user_id } })}
        >
          <Text style={styles.text}>{account.name}</Text>
        </Pressable>
      ))}
      <View style={{ gap: 8 }}>
        <Button label={t("addInterviewer")} onPress={() => router.push("/sign-in")} />
        <Button kind="secondary" label={t("settings")} onPress={() => router.push("/settings")} />
      </View>
    </Screen>
  );
}
