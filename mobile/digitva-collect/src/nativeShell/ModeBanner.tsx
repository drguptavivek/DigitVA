import { usePathname } from "expo-router";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { t } from "../i18n";
import { typography, useTheme } from "../theme";
import { useShell } from "./shellContext";

export type ModeBannerMode = "standalone" | "demo";

type ModeBannerAccount = { user_id: string; standalone?: boolean };

export interface ModeBannerState {
  pathname: string;
  userId?: string;
  accounts: readonly ModeBannerAccount[];
  slot?: "active" | "demo";
  standaloneAvailable: boolean;
}

const normalizePath = (pathname: string) => pathname.replace(/\/$/, "") || "/";

/** Resolve the mode without inferring it from connectivity or a server URL. */
export function resolveModeBanner({ pathname, userId, accounts, slot, standaloneAvailable }: ModeBannerState): ModeBannerMode | undefined {
  const route = normalizePath(pathname);
  if (slot === "demo" || route === "/demo") return "demo";
  if (!standaloneAvailable) return undefined;

  const account = userId ? accounts.find((item) => item.user_id === userId) : undefined;
  const standaloneAccount = account?.standalone === true;
  const setupRoute = route === "/standalone-setup";
  const standaloneRoute = route === "/standalone";
  const accountList = route === "/" && accounts.some((item) => item.standalone === true);
  return setupRoute || standaloneRoute || accountList || standaloneAccount ? "standalone" : undefined;
}

export function ModeBanner() {
  const pathname = usePathname();
  const shell = useShell();
  // Browser AppState deliberately has no native accounts/slot; defaults keep the shared root web-safe.
  const { accounts = [], slot, standaloneAvailable = false } = useAppState();
  const mode = resolveModeBanner({ pathname, userId: shell.userId, accounts, slot, standaloneAvailable });
  const { ui } = useTheme();
  if (!mode) return null;

  const standalone = mode === "standalone";
  return (
    <View
      accessibilityRole="header"
      style={{ backgroundColor: standalone ? ui.warning : ui.accent, borderBottomWidth: 1, borderBottomColor: standalone ? ui.warningBorder : ui.border, paddingHorizontal: 12, paddingVertical: 6 }}
    >
      <Text style={{ ...typography.subhead, fontWeight: "700", color: standalone ? ui.warningForeground : ui.accentForeground }}>
        {t(standalone ? "modeStandalone" : "modeDemo")}
      </Text>
    </View>
  );
}
