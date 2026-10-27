/**
 * The "DEMO" badge in the app header, shown only against the public demo
 * (docs/policy/public-demo.md; the Flask navbar shows the same badge). `server`
 * is the account's server origin on a device, the page's own origin on the web;
 * both are compared with the build's demo origin (src/enrolment.ts isDemoServer).
 * The header strip is brand blue in both colour modes, so the light tokens apply.
 */
import { useEffect } from "react";
import { Platform, Text, View } from "react-native";

import { isDemoServer } from "./enrolment";
import { t } from "./i18n";
import { spacing, typography, ui } from "./theme";

export default function DemoBadge({ server }: { server: string | undefined }) {
  if (!isDemoServer(server, __DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER)) return null;
  return (
    <View
      accessible
      accessibilityLabel={t("demoBadge")}
      style={{ backgroundColor: ui.light.warning, borderColor: ui.light.warningBorder, borderWidth: 1, borderRadius: 6, paddingHorizontal: spacing.xs, paddingVertical: 2 }}
    >
      <Text style={{ ...typography.caption, fontWeight: "700", color: ui.light.warningForeground }}>{t("demoHeaderBadge")}</Text>
    </View>
  );
}

/** "DEMO - " in front of the browser tab title on the public demo, kept there
 * as the router changes the title (matches the Flask pages' title prefix). */
export const DEMO_TITLE_PREFIX = "DEMO - ";

export function withDemoPrefix(title: string): string {
  return title.startsWith(DEMO_TITLE_PREFIX) ? title : DEMO_TITLE_PREFIX + title;
}

export function useDemoDocumentTitle() {
  useEffect(() => {
    if (Platform.OS !== "web" || typeof document === "undefined") return undefined;
    if (!isDemoServer(window.location.origin, __DEV__, process.env.EXPO_PUBLIC_DEMO_SERVER)) return undefined;
    const apply = () => {
      const next = withDemoPrefix(document.title);
      if (next !== document.title) document.title = next;
    };
    apply();
    const observer = new MutationObserver(apply);
    observer.observe(document.head, { subtree: true, childList: true, characterData: true });
    return () => observer.disconnect();
  }, []);
}
