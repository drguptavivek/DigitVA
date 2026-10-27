import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { ActivityIndicator, Platform, Text, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider, useAppState } from "../src/AppState";
import { isPlusVariant } from "../src/appVariant";
import { applyScreenCaptureBlock } from "../src/screenCapture";
import { useTheme } from "../src/theme";
import { useWhoWebTheme } from "../src/whoWebTheme";
import { ToastProvider } from "../src/toast";
import { t } from "../src/i18n";
import NativeTermsGate from "../src/NativeTermsGate";
import NativeCollectionGate from "../src/NativeCollectionGate";
import { ShellHeader, ShellRoot, ShellTabs } from "../src/nativeShell/chrome";
import { ClockWarning } from "../src/nativeShell/ClockNotice";
if (Platform.OS === "android") require("../src/notificationTask");
let notificationRegistrationWarningShown = false;

/** Every touch anywhere restarts the idle-lock timer; the touch itself goes on to its target. */
function ActivityRoot() {
  const { activity, ready, accounts } = useAppState();
  const { colors } = useTheme();
  useEffect(() => {
    if (!ready || Platform.OS !== "android") return;
    const eligible = accounts.some(
      (account) => !account.standalone && !account.needs_sign_in && !account.terms_required && !account.access_blocked,
    );
    const { syncNotificationTaskRegistration } = require(
      "../src/notificationTask",
    ) as typeof import("../src/notificationTask");
    void syncNotificationTaskRegistration(eligible).catch(() => {
      if (notificationRegistrationWarningShown) return;
      notificationRegistrationWarningShown = true;
      console.warn("Background notification polling could not be configured.");
    });
  }, [accounts, ready]);
  if (Platform.OS === "web" && !ready) {
    return <View accessibilityRole="progressbar" accessibilityLabel={t("loading")}
      style={{ flex: 1, alignItems: "center", justifyContent: "center", gap: 12, backgroundColor: colors.background }}>
      <ActivityIndicator color={colors.accent} />
      <Text style={{ color: colors.textMuted }}>{t("loading")}</Text>
    </View>;
  }
  return (
    <View
      style={{ flex: 1 }}
      onStartShouldSetResponderCapture={() => {
        activity();
        return false;
      }}
    >
      <ShellHeader />
      <ClockWarning />
      <NativeTermsGate>
        <Stack
          screenOptions={{ headerShown: false, animation: "none" }}
          screenLayout={({ children, route }) => (
            <NativeCollectionGate routeName={route.name} routeParams={route.params}>
              {children}
            </NativeCollectionGate>
          )}
        />
      </NativeTermsGate>
      <ShellTabs />
    </View>
  );
}

export default function RootLayout() {
  const theme = useTheme();
  useWhoWebTheme();
  useEffect(() => {
    applyScreenCaptureBlock();
  }, []);
  // Collect Plus: load the offline engine in the background (its own process) while the coder signs in and browses.
  useEffect(() => {
    if (Platform.OS !== "android" || !isPlusVariant()) return undefined;
    return (require("../src/offlineEngine") as typeof import("../src/offlineEngine")).scheduleEngineWarmUp();
  }, []);
  return (
    <SafeAreaProvider>
      <AppStateProvider>
        <StatusBar style={theme.mode === "dark" ? "light" : "dark"} />
        <ToastProvider>
          <ShellRoot>
            <ActivityRoot />
          </ShellRoot>
        </ToastProvider>
      </AppStateProvider>
    </SafeAreaProvider>
  );
}
