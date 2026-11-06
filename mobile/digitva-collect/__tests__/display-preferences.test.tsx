/**
 * Settings > Display (docs/policy/expo-client.md "Text size, high contrast and screen readers"): the Text size
 * factor times the phone's font scale, capped at 2.0; the High contrast palette, on when the phone asks for more
 * contrast until the user chooses; both stored on the device only.
 */
import React from "react";
import { AccessibilityInfo, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

let mockFontScale = 1;
jest.mock("react-native/Libraries/Utilities/useWindowDimensions", () => ({
  __esModule: true,
  default: () => ({ width: 375, height: 800, scale: 2, fontScale: mockFontScale }),
}));
const mockStored = new Map<string, string>();
jest.mock("expo-secure-store", () => ({
  getItemAsync: jest.fn(async (key: string) => mockStored.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => { mockStored.set(key, value); }),
}));

import { setItemAsync } from "expo-secure-store";

// The phone asks for more contrast (iOS Increase Contrast; jest-expo runs as iOS). Set before the theme module
// loads (a require, not a hoisted import), since it reads the setting once at load.
jest.mocked(AccessibilityInfo.isDarkerSystemColorsEnabled).mockResolvedValue(true);
const { MAX_TEXT_SCALE, scaleTypography, tokenTextScale, typography, ui, uiHighContrast, useTheme, __setDisplayForTest } =
  require("../src/theme") as typeof import("../src/theme");
const { whoFormTheme } = require("../src/whoWebTheme") as typeof import("../src/whoWebTheme");

type Seen = ReturnType<typeof import("../src/theme").useTheme>;
let seen!: Seen;
function Probe() {
  seen = useTheme();
  return <Text>{seen.typography.body.fontSize}</Text>;
}
let tree: ReactTestRenderer | undefined;
async function render() {
  await act(async () => { tree = create(<Probe />); for (let i = 0; i < 10; i += 1) await Promise.resolve(); });
}
afterEach(() => {
  act(() => tree?.unmount());
  tree = undefined;
});

// First: the module read the phone's contrast setting when it loaded (later tests reset the store).
it("turns high contrast on at start when the phone asks for more contrast and nothing is stored", async () => {
  await render();
  expect(AccessibilityInfo.isDarkerSystemColorsEnabled).toHaveBeenCalled();
  expect(seen.highContrast).toBe(true);
  expect(seen.ui).toBe(uiHighContrast[seen.mode]);
});

describe("text size scale", () => {
  it("is the choice when the phone is at its default size", () => {
    expect([tokenTextScale("small", 1), tokenTextScale("medium", 1), tokenTextScale("large", 1)]).toEqual([0.9, 1, 1.2]);
  });

  it("caps the choice times the phone's font scale at 2.0", () => {
    expect(MAX_TEXT_SCALE).toBe(2);
    // Large on a phone at 1.8x: 2.16x would be drawn, so the tokens carry 2.0 / 1.8 and the phone multiplies back to 2.0.
    expect(tokenTextScale("large", 1.8) * 1.8).toBeCloseTo(2);
    expect(tokenTextScale("medium", 2.5) * 2.5).toBeCloseTo(2);
    // Under the cap the phone's scale is left to the phone.
    expect(tokenTextScale("large", 1.5)).toBeCloseTo(1.2);
  });

  it("treats a missing or zero phone scale as 1", () => {
    expect(tokenTextScale("large", 0)).toBe(1.2);
  });

  it("scales every text token's size and line height", () => {
    const large = scaleTypography(1.2);
    expect(large.typography.body).toMatchObject({ fontSize: 19, lineHeight: 29, fontWeight: typography.body.fontWeight });
    expect(large.fontSize.caption).toBe(14.5);
    expect(scaleTypography(1).typography).toEqual(typography);
  });
});

describe("useTheme", () => {
  beforeEach(() => {
    mockFontScale = 1;
    mockStored.clear();
    jest.mocked(setItemAsync).mockClear();
    __setDisplayForTest({ textSize: "medium", highContrast: "system", osHighContrast: false });
  });

  it("serves scaled tokens for the chosen text size and stores it on the device", async () => {
    await render();
    expect(seen.typography.body.fontSize).toBe(16);
    await act(async () => { await seen.setTextSize("large"); });
    expect(seen.textSize).toBe("large");
    expect(seen.textScale).toBe(1.2);
    expect(seen.typography.body.fontSize).toBe(19);
    expect(setItemAsync).toHaveBeenCalledWith("ui_text_size", "large");
    // The WHO form gets the same factor.
    expect(whoFormTheme(seen).fontScale).toBe(1.2);
  });

  it("follows the phone's font scale up to the cap", async () => {
    mockFontScale = 2;
    __setDisplayForTest({ textSize: "large" });
    await render();
    expect(seen.textScale * 2).toBeCloseTo(2);
  });

  it("starts high contrast when the phone asks for it, and the user's choice then wins", async () => {
    __setDisplayForTest({ osHighContrast: true });
    await render();
    expect(seen.highContrast).toBe(true);
    expect(seen.ui).toBe(uiHighContrast[seen.mode]);
    expect(seen.focusWidth).toBe(3);
    await act(async () => { await seen.setHighContrast(false); });
    expect(seen.highContrast).toBe(false);
    expect(seen.ui).toBe(ui[seen.mode]);
    expect(seen.focusWidth).toBe(2);
    expect(setItemAsync).toHaveBeenCalledWith("ui_high_contrast", "off");
    // The phone's setting changing again does not override the stored choice.
    await act(async () => { __setDisplayForTest({ osHighContrast: false }); __setDisplayForTest({ osHighContrast: true }); });
    expect(seen.highContrast).toBe(false);
    await act(async () => { await seen.setHighContrast(true); });
    expect(seen.highContrast).toBe(true);
    expect(setItemAsync).toHaveBeenLastCalledWith("ui_high_contrast", "on");
  });

});
