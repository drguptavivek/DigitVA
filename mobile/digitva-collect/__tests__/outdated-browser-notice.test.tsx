import React, { act } from "react";
import { create, type ReactTestRenderer } from "react-test-renderer";

import { OutdatedBrowserNotice } from "../src/OutdatedBrowserNotice";
import { setUiLocale } from "../src/i18n";

beforeEach(() => setUiLocale("en"));

test("the warning icon opens a one-button dialog that explains the old browser", () => {
  let tree!: ReactTestRenderer;
  act(() => { tree = create(<OutdatedBrowserNotice />); });
  const icon = tree.root.find((node) => node.props.testID === "outdated-browser-warning" && typeof node.props.onPress === "function");
  expect(icon.props.accessibilityLabel).toBe("Browser out of date");
  const buttonLabels = () => tree.root.findAll((node) => typeof node.props.label === "string" && typeof node.props.onPress === "function").map((node) => node.props.label);
  expect(buttonLabels()).toEqual([]);
  act(() => icon.props.onPress());
  expect(JSON.stringify(tree.toJSON())).toContain("Update iOS");
  expect([...new Set(buttonLabels())]).toEqual(["OK"]);
  const ok = tree.root.findAll((node) => node.props.label === "OK" && typeof node.props.onPress === "function")[0];
  act(() => ok.props.onPress());
  expect(JSON.stringify(tree.toJSON())).not.toContain("Update iOS");
});
