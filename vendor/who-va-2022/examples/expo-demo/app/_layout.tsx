import { Stack } from "expo-router";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { DemoStateProvider } from "../components/DemoState";

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <DemoStateProvider>
        <Stack screenOptions={{ headerShown: false }} />
      </DemoStateProvider>
    </SafeAreaProvider>
  );
}
