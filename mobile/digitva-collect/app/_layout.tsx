import { Stack } from "expo-router";
import { preventScreenCaptureAsync } from "expo-screen-capture";
import { StatusBar } from "expo-status-bar";
import { useEffect } from "react";
import { View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider, useAppState } from "../src/AppState";

// FLAG_SECURE on the whole app: no screenshots, blank in recent apps. A debug
// build may opt out for emulator screenshots (EXPO_PUBLIC_ALLOW_SCREENSHOTS=1
// at Metro start); __DEV__ is false in release, so release always blocks.
const allowScreenshots = __DEV__ && process.env.EXPO_PUBLIC_ALLOW_SCREENSHOTS === "1";

/** Every touch anywhere restarts the idle-lock timer; the touch itself goes on to its target. */
function ActivityRoot() {
  const { activity } = useAppState();
  return (
    <View
      style={{ flex: 1 }}
      onStartShouldSetResponderCapture={() => {
        activity();
        return false;
      }}
    >
      <Stack screenOptions={{ headerShown: false }} />
    </View>
  );
}

export default function RootLayout() {
  useEffect(() => {
    if (!allowScreenshots) void preventScreenCaptureAsync();
  }, []);
  return (
    <SafeAreaProvider>
      <AppStateProvider>
        <StatusBar style="dark" />
        <ActivityRoot />
      </AppStateProvider>
    </SafeAreaProvider>
  );
}
