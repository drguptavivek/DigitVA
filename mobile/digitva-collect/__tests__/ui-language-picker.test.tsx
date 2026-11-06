/**
 * The app-language picker (digitva-s028, docs/policy/expo-client.md "Adding a UI language"): one list from
 * useUiLanguages(), a segmented control for two or three languages and a list sheet from four, "Machine-translated"
 * under a language not fully reviewed; and S1: a SegmentedControl inside a Card marks its choice with the primary
 * tint, while on the canvas it keeps the white segment.
 */
import React from "react";
import { act, create, type ReactTestInstance, type ReactTestRenderer } from "react-test-renderer";
import { StyleSheet, Text } from "react-native";

const mockChooseLocale = jest.fn(async (_code: string) => undefined);
let mockLocale = "en";
jest.mock("../src/AppState", () => ({ useAppState: () => ({ uiLocale: mockLocale, chooseUiLocale: mockChooseLocale }) }));
jest.mock("react-native-safe-area-context", () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("expo-router", () => ({
  useRouter: () => ({}),
  usePathname: () => "/sign-in",
  useGlobalSearchParams: () => ({}),
  useNavigationContainerRef: () => ({ current: null }),
}));

import themeEn from "../src/strings/theme-en.json";
import { setServerUiLanguages, type UiLanguage } from "../src/i18n";
import { LanguageButton } from "../src/nativeShell/NativeChrome";
import { ui } from "../src/theme";
import { Card, SegmentedControl } from "../src/ui";
import { UiLanguageRow } from "../src/ui/LanguagePicker";

const served = (code: string, label: string, tag: string, reviewed: number): UiLanguage => ({
  code, label, language: tag, direction: "ltr", reviewed, bundled: false, version: "a".repeat(64),
});
const TAMIL = served("ta", "தமிழ்", "ta-IN", 1);
const MARATHI = served("mr", "मराठी", "mr-IN", 0.4);

const mounted: ReactTestRenderer[] = [];
async function render(node: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(node); });
  mounted.push(tree);
  return tree;
}
const hostRadios = (tree: ReactTestRenderer) => tree.root.findAll((n) => typeof n.type === "string" && n.props.accessibilityRole === "radio");
const textOf = (node: ReactTestInstance) => node.findAllByType(Text).map((n) => n.props.children).flat().join("");
const out = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());

beforeEach(async () => {
  // Unmount first: the list below notifies every mounted picker.
  await act(async () => { mounted.splice(0).forEach((tree) => tree.unmount()); });
  mockChooseLocale.mockClear();
  mockLocale = "en";
  setServerUiLanguages(false, []);
});

describe("S1: SegmentedControl selected segment", () => {
  const options = [{ value: "a", label: "One" }, { value: "b", label: "Two" }];
  it("is the primary tint with primary text inside a Card", async () => {
    const tree = await render(<Card grouped><SegmentedControl accessibilityLabel="Choice" options={options} value="a" onChange={() => undefined} /></Card>);
    const [selected, other] = hostRadios(tree);
    expect(selected.props.accessibilityState.checked).toBe(true);
    expect(StyleSheet.flatten(selected.props.style).backgroundColor).toBe(ui.light.primaryTint);
    expect(StyleSheet.flatten(selected.findByType(Text).props.style).color).toBe(ui.light.primary);
    expect(StyleSheet.flatten(other.props.style).backgroundColor).toBe("transparent");
  });
  it("stays the white card tone with ink text on the canvas (Sign in)", async () => {
    const tree = await render(<SegmentedControl accessibilityLabel="Choice" options={options} value="a" onChange={() => undefined} />);
    const [selected] = hostRadios(tree);
    expect(StyleSheet.flatten(selected.props.style).backgroundColor).toBe(ui.light.card);
    expect(StyleSheet.flatten(selected.findByType(Text).props.style).color).toBe(ui.light.foreground);
  });
});

describe("UiLanguageRow", () => {
  it("offers the two bundled languages as a segmented control, each name tagged with its language", async () => {
    const tree = await render(<Card grouped><UiLanguageRow label="App language" /></Card>);
    expect(tree.root.findAllByType(SegmentedControl)).toHaveLength(1);
    const radios = hostRadios(tree);
    expect(radios.map(textOf)).toEqual(["English", "हिन्दी"]);
    expect(radios[1].props.accessibilityLanguage).toBe("hi-IN");
    expect(tree.root.findAll((n) => n.props.testID === "language-sheet")).toHaveLength(0);
    await act(async () => { tree.root.findAll((n) => n.props.accessibilityLabel === "हिन्दी" && typeof n.props.onPress === "function")[0].props.onPress(); });
    expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  });

  it("keeps the segmented control at three and says when the current language is machine-translated", async () => {
    setServerUiLanguages(true, [MARATHI]);
    mockLocale = "mr";
    const tree = await render(<Card grouped><UiLanguageRow label="App language" /></Card>);
    expect(hostRadios(tree).map(textOf)).toEqual(["English", "हिन्दी", "मराठी"]);
    expect(out(tree)).toContain(themeEn.uiLanguageMachineTranslated);
  });

  it("switches to a list sheet at four languages, labelling only the unreviewed one", async () => {
    setServerUiLanguages(true, [TAMIL, MARATHI]);
    const tree = await render(<Card grouped><UiLanguageRow label="App language" /></Card>);
    expect(tree.root.findAllByType(SegmentedControl)).toHaveLength(0);
    // The row names the current language and opens the sheet.
    const row = tree.root.findAll((n) => n.props.accessibilityLabel === "App language, English" && typeof n.props.onPress === "function")[0];
    expect(row).toBeDefined();
    expect(out(tree)).not.toContain(themeEn.uiLanguageMachineTranslated);
    await act(async () => { row.props.onPress(); });
    const sheet = tree.root.findAll((n) => n.props.testID === "language-sheet")[0];
    expect(sheet).toBeDefined();
    const rows = sheet.findAll((n) => n.props.accessibilityRole === "radio" && typeof n.props.onPress === "function");
    expect(rows.map((n) => n.props.accessibilityLabel)).toEqual(["English", "हिन्दी", "தமிழ்", "मराठी"]);
    expect(rows.map((n) => n.props.accessibilityLanguage)).toEqual(["en-IN", "hi-IN", "ta-IN", "mr-IN"]);
    expect(rows.map((n) => n.props.accessibilityHint)).toEqual([undefined, undefined, undefined, themeEn.uiLanguageMachineTranslated]);
    expect(rows[0].props.accessibilityState.checked).toBe(true);
    await act(async () => { rows[2].props.onPress(); });
    expect(mockChooseLocale).toHaveBeenCalledWith("ta");
  });
});

describe("LanguageButton (pre-login header)", () => {
  it("keeps the menu for two languages and opens the list sheet from four", async () => {
    const two = await render(<LanguageButton color="#000" />);
    await act(async () => { two.root.findAll((n) => n.props.accessibilityState?.expanded === false && typeof n.props.onPress === "function")[0].props.onPress(); });
    expect(two.root.findAll((n) => n.props.accessibilityRole === "menuitem" && typeof n.props.onPress === "function").map((n) => n.props.accessibilityLabel)).toEqual(["English", "हिन्दी"]);
    expect(two.root.findAll((n) => n.props.testID === "language-sheet")).toHaveLength(0);

    await act(async () => { setServerUiLanguages(true, [TAMIL, MARATHI]); });
    const four = await render(<LanguageButton color="#000" />);
    await act(async () => { four.root.findAll((n) => n.props.accessibilityState?.expanded === false && typeof n.props.onPress === "function")[0].props.onPress(); });
    expect(four.root.findAll((n) => n.props.testID === "language-sheet")).not.toHaveLength(0);
    expect(four.root.findAll((n) => n.props.accessibilityRole === "menuitem")).toHaveLength(0);
    expect(out(four)).toContain(themeEn.uiLanguageMachineTranslated);
  });
});
