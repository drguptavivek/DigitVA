import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { ActivityIndicator, Platform, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider, useAppState } from "../src/AppState";
import { applyScreenCaptureBlock } from "../src/screenCapture";
import { useTheme } from "../src/theme";
import { useWhoWebTheme } from "../src/whoWebTheme";
import { ToastProvider } from "../src/toast";
import NativeTermsGate from "../src/NativeTermsGate";
import NativeCollectionGate from "../src/NativeCollectionGate";
import AppHeader, { BottomTabs } from "../src/web/AppHeader";
if (Platform.OS === "android") require("../src/notificationTask");
let notificationRegistrationWarningShown = false;

/** Every touch anywhere restarts the idle-lock timer; the touch itself goes on to its target. */
function ActivityRoot() {
  const { activity, ready, accounts } = useAppState();
  useEffect(() => {
    if (!ready || Platform.OS !== "android") return;
    const eligible = accounts.some(
      (account) => !account.needs_sign_in && !account.terms_required && !account.access_blocked,
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
    return <View style={{ flex: 1, alignItems: "center", justifyContent: "center" }}><ActivityIndicator /></View>;
  }
  return (
    <View
      style={{ flex: 1 }}
      onStartShouldSetResponderCapture={() => {
        activity();
        return false;
      }}
    >
      <AppHeader />
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
      <BottomTabs />
    </View>
  );
}

export default function RootLayout() {
  const theme = useTheme();
  useWhoWebTheme();
  useEffect(() => {
    applyScreenCaptureBlock();
  }, []);
  return (
    <SafeAreaProvider>
      <AppStateProvider>
        <StatusBar style={theme.mode === "dark" ? "light" : "dark"} />
        <ToastProvider>
          <ActivityRoot />
        </ToastProvider>
      </AppStateProvider>
    </SafeAreaProvider>
  );
}
