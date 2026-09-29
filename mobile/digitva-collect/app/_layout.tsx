import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { AppStateProvider } from "../src/AppState";

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <AppStateProvider>
        <StatusBar style="dark" />
        <Stack screenOptions={{ headerShown: false }} />
      </AppStateProvider>
    </SafeAreaProvider>
  );
}
