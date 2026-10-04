import { Stack } from "expo-router";
import { preventScreenCaptureAsync } from "expo-screen-capture";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { ActivityIndicator, Platform, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider, useAppState } from "../src/AppState";
import { useTheme } from "../src/theme";
import NativeTermsGate from "../src/NativeTermsGate";
if (Platform.OS === "android") require("../src/notificationTask");
let notificationRegistrationWarningShown = false;

// FLAG_SECURE on the whole app: no screenshots, blank in recent apps. A debug
// build may opt out for emulator screenshots (EXPO_PUBLIC_ALLOW_SCREENSHOTS=1
// at Metro start); __DEV__ is false in release, so release always blocks.
const allowScreenshots = __DEV__ && process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS === "1";

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
      <NativeTermsGate><Stack screenOptions={{ headerShown: false }} /></NativeTermsGate>
    </View>
  );
}

export default function RootLayout() {
  const theme = useTheme();
  useEffect(() => {
    if (Platform.OS !== "web" && !allowScreenshots) void preventScreenCaptureAsync();
  }, []);
  return (
    <SafeAreaProvider>
      <AppStateProvider>
        <StatusBar style={theme.mode === "dark" ? "light" : "dark"} />
        <ActivityRoot />
      </AppStateProvider>
    </SafeAreaProvider>
  );
}
