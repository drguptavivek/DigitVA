import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Pressable, Text, View } from "react-native";

const mockSecureStore = new Map<string, string>();
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 24, bottom: 12, left: 0, right: 0 }) }));
jest.mock("../src/nativeShell/shellContext", () => ({ useShell: () => ({ header: {}, tabs: {} }) }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [] }) }));
let mockPlus = true;
jest.mock("../src/appVariant", () => ({ isPlusVariant: () => mockPlus }));
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

// Owner 2026-11-21: coding is on by default in both variants, with no first-run question; a stored choice still wins.
it.each([[false, undefined, true], [false, "disabled", false], [true, undefined, true], [true, "disabled", false]] as const)("never shows the gate (Plus %s, stored %s)", async (plus, stored, enabled) => {
  mockPlus = plus;
  jest.resetModules();
  mockSecureStore.clear();
  if (stored) mockSecureStore.set("digitva.icd11-doris-enabled.v1", stored);
  const Gate = require("../src/NativeIcd11DorisFirstLaunchGate.native").default;
  const pref = require("../src/icd11DorisPreference");
  const R = require("react");
  const { act: act2, create: create2 } = require("react-test-renderer");
  let tree!: ReactTestRenderer;
  await act2(async () => { tree = create2(R.createElement(Gate, null, R.createElement(Text, null, "App home"))); });
  expect(JSON.stringify(tree.toJSON())).toContain("App home");
  expect(JSON.stringify(tree.toJSON())).not.toContain(en.icd11DorisPreferenceTitle);
  expect(await pref.isIcd11DorisEnabled()).toBe(enabled);
  mockPlus = true;
});
