import React from "react";
import { act, create } from "react-test-renderer";
import { Text } from "react-native";

const mockSecureStore = new Map<string, string>();
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/nativeShell/ModeBanner", () => ({ ModeBanner: () => null }));
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => mockSecureStore.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => { mockSecureStore.set(key, value); }),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) => {
    const React = require("react");
    const { Pressable, Text } = require("react-native");
    return React.createElement(Pressable, { accessibilityLabel: label, onPress, disabled }, React.createElement(Text, null, label));
  },
  Screen: ({ title, children }: { title: string; children: unknown }) => {
    const React = require("react");
    const { Text, View } = require("react-native");
    return React.createElement(View, null, React.createElement(Text, null, title), children);
  },
  useUiStyles: () => ({ text: {}, muted: {}, error: {} }),
}));

import NativeIcd11DorisFirstLaunchGate from "../src/NativeIcd11DorisFirstLaunchGate.native";
import { isIcd11DorisEnabled } from "../src/icd11DorisPreference";
import en from "../src/strings/en.json";

it("enables coding only after the first-run choice is saved", async () => {
  mockSecureStore.clear();
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<NativeIcd11DorisFirstLaunchGate><Text>App home</Text></NativeIcd11DorisFirstLaunchGate>);
  });
  const enable = tree.root.findByProps({ accessibilityLabel: en.icd11DorisPreferenceEnable });
  await act(async () => { await enable.props.onPress(); });
  expect(mockSecureStore.get("digitva.icd11-doris-enabled.v1")).toBe("enabled");
  expect(await isIcd11DorisEnabled()).toBe(true);
  expect(JSON.stringify(tree.toJSON())).toContain("App home");
});
