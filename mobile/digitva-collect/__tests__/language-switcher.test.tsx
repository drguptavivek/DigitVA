import React from "react";
import { act, create } from "react-test-renderer";

const mockChooseLocale = jest.fn().mockResolvedValue(undefined);
jest.mock("expo-router", () => ({ usePathname: () => "/collection", useRouter: () => ({}) }));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ uiLocale: "en", chooseUiLocale: mockChooseLocale }) }));
jest.mock("../src/theme", () => ({ useTheme: () => ({ colors: {} }) }));
jest.mock("../src/ui", () => ({ Button: () => null, Screen: () => null, useUiStyles: () => ({}) }));

import { UiLanguageSwitcher } from "../src/web/common";

it("keeps retained screens' menu and focus targets distinct", async () => {
  let tree!: ReturnType<typeof create>;
  await act(async () => { tree = create(<><UiLanguageSwitcher /><UiLanguageSwitcher /></>); });
  const anchors = tree.root.findAll(node => typeof node.props?.nativeID === "string" && node.props.nativeID.startsWith("ui-language-menu-"));
  const triggers = tree.root.findAll(node => typeof node.props?.nativeID === "string" && node.props.nativeID.startsWith("ui-language-trigger-") && typeof node.props.onPress === "function");
  expect(new Set(anchors.map(node => node.props.nativeID)).size).toBe(2);
  expect(new Set(triggers.map(node => node.props.nativeID)).size).toBe(2);
  await act(async () => { triggers[1].props.onPress(); });
  const hindi = tree.root.findAll(node => node.props?.accessibilityRole === "radio" && node.props.accessibilityLabel === "हिन्दी" && typeof node.props.onPress === "function")[0];
  await act(async () => { await hindi.props.onPress(); });
  expect(mockChooseLocale).toHaveBeenCalledWith("hi");
  await act(async () => { tree.unmount(); });
});
