import React from "react";
import { act, create } from "react-test-renderer";
import { Text } from "react-native";

// Native path: no browser storage, the stored theme is dark and the OS scheme is light.
jest.mock("react-native/Libraries/Utilities/useColorScheme", () => ({ __esModule: true, default: () => "light" }));
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => (key === "ui_theme" ? "dark" : null)),
  setItemAsync: jest.fn(async () => undefined),
}));

test("a locale change after the first async read keeps the stored theme", async () => {
  const { useTheme } = require("../src/theme") as typeof import("../src/theme");
  const { setUiLocalePreference, peekUiTheme } = require("../src/preferences") as typeof import("../src/preferences");
  function Probe() { return <Text>{useTheme().mode}</Text>; }
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Probe />); for (let i = 0; i < 5; i += 1) await Promise.resolve(); });
  // The async read has landed: dark is shown and now known synchronously.
  expect(JSON.stringify(tree.toJSON())).toContain("dark");
  expect(peekUiTheme()).toBe("dark");
  await act(async () => { await setUiLocalePreference("hi"); });
  expect(JSON.stringify(tree.toJSON())).toContain("dark");
  expect(JSON.stringify(tree.toJSON())).not.toContain("light");
  tree.unmount();
});
