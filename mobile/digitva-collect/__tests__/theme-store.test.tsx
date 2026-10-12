import React from "react";
import { act, create } from "react-test-renderer";
import { Text } from "react-native";

import { __setThemePreferenceForTest, palette, useTheme } from "../src/theme";

// Stored preference is dark while the OS scheme is light: any system-first paint would show light.
jest.mock("react-native/Libraries/Utilities/useColorScheme", () => ({ __esModule: true, default: () => "light" }));
jest.mock("../src/preferences", () => ({
  peekUiTheme: () => "dark",
  getUiTheme: jest.fn(async () => "dark"),
  setUiTheme: jest.fn(async () => undefined),
  subscribeUiPreferences: () => () => undefined
}));

const seen: string[] = [];
function Probe() {
  const { mode, colors } = useTheme();
  seen.push(colors.background);
  return <Text>{mode}</Text>;
}

test("first render uses the primed stored preference and never flips", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<Probe />); await Promise.resolve(); });
  expect(seen.length).toBeGreaterThan(0);
  expect(new Set(seen)).toEqual(new Set([palette.dark.background]));
  tree.unmount();
});

test("hook instances agree and a preference change updates all of them together", async () => {
  let a!: ReturnType<typeof create>;
  let b!: ReturnType<typeof create>;
  await act(async () => { a = create(<Probe />); b = create(<Probe />); });
  expect(JSON.stringify(a.toJSON())).toBe(JSON.stringify(b.toJSON()));
  expect(JSON.stringify(a.toJSON())).toContain("dark");
  await act(async () => { __setThemePreferenceForTest("light"); });
  expect(JSON.stringify(a.toJSON())).toContain("light");
  expect(JSON.stringify(b.toJSON())).toContain("light");
  await act(async () => { __setThemePreferenceForTest("dark"); });
});
