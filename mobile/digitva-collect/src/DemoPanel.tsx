/**
 * The public-demo badge and its two browser links, shown on a phone enrolled
 * on the demo server (src/enrolment.ts isDemoServer). The links open in the
 * system browser: the dashboard is public, My reports needs a web sign-in
 * there (the app's session is not shared with the browser).
 */
import { useState } from "react";
import { Linking, Text, View } from "react-native";

import { DEMO_PAGES, demoPageUrl } from "./demo";
import { isDemoServer } from "./enrolment";
import { t } from "./i18n";
import { Button, useUiStyles } from "./ui";

export default function DemoPanel({ server }: { server: string | undefined }) {
  const styles = useUiStyles();
  const [failed, setFailed] = useState(false);
  if (!server || !isDemoServer(server, __DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER)) return null;
  async function open(path: (typeof DEMO_PAGES)[keyof typeof DEMO_PAGES]) {
    setFailed(false);
    try {
      await Linking.openURL(demoPageUrl(path, server));
    } catch {
      setFailed(true);
    }
  }
  return (
    <View style={styles.card}>
      <Text style={styles.text} accessibilityRole="header">{t("demoBadge")}</Text>
      <Button kind="secondary" label={t("demoLinkDashboard")} onPress={() => void open(DEMO_PAGES.dashboard)} />
      <Button kind="secondary" label={t("demoLinkReports")} onPress={() => void open(DEMO_PAGES.reports)} />
      {failed ? <Text style={styles.error}>{t("demoLinkFailed")}</Text> : null}
    </View>
  );
}
