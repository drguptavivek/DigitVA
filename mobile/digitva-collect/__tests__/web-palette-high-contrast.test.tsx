/** The browser workspace follows the High contrast switch (docs/policy/expo-client.md), and the picker page is told. */
import React from "react";
import { Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { uiHighContrast, ui, __setDisplayForTest } from "../src/theme";
import { useWebPalette, webPalette, webPaletteHighContrast, type WebPalette } from "../src/workspace/webPalette";

let seen!: WebPalette;
function Probe() {
  seen = useWebPalette();
  return <Text>{seen.page}</Text>;
}

async function palette(highContrast: boolean): Promise<WebPalette> {
  __setDisplayForTest({ theme: "light", highContrast: highContrast ? "on" : "off" });
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<Probe />); });
  act(() => tree.unmount());
  return seen;
}

it("useWebPalette returns the high-contrast tokens when high contrast is on, the normal ones when off", async () => {
  expect(await palette(true)).toBe(webPaletteHighContrast.light);
  expect(seen.page).toBe(uiHighContrast.light.page);
  expect(seen.selected).toBe(uiHighContrast.light.primary);
  expect(await palette(false)).toBe(webPalette.light);
  expect(seen.page).toBe(ui.light.page);
  expect(webPaletteHighContrast.light.page).not.toBe(webPalette.light.page);
});

it("selected category and DEMO badge match the phone in both modes", () => {
  for (const mode of ["light", "dark"] as const) {
    expect(webPalette[mode]).toMatchObject({ selected: ui[mode].primary, onSelected: ui[mode].primaryForeground, demo: ui[mode].warning, onDemo: ui[mode].warningForeground });
  }
});
