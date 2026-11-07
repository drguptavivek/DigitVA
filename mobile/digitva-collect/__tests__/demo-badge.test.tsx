import React from "react";
import TestRenderer, { act } from "react-test-renderer";

jest.mock("react-native", () => ({ Platform: { OS: "android" }, Text: "text", View: "view", useWindowDimensions: () => ({ fontScale: 2 }) }));
jest.mock("../src/theme", () => ({
  spacing: { xs: 4 }, typography: { caption: {} },
  ui: { light: { warning: "w", warningBorder: "b", warningForeground: "f" } },
}));
jest.mock("../src/i18n", () => ({ t: (key: string) => key }));

import DemoBadge from "../src/DemoBadge";
import { DEMO_SERVER } from "../src/enrolment";

const texts = (server?: string) => {
  let tree!: TestRenderer.ReactTestRenderer;
  act(() => { tree = TestRenderer.create(<DemoBadge server={server} />); });
  return tree.root.findAllByType("text" as never).map((n) => n.props.children);
};

describe("DemoBadge", () => {
  it("shows DEMO on the demo origin", () => {
    expect(texts(DEMO_SERVER)).toContain("demoHeaderBadge");
  });
  it("renders nothing elsewhere or without a server", () => {
    expect(texts("https://digitva.causeofdeathindia.com")).toEqual([]);
    expect(texts(undefined)).toEqual([]);
  });
});

describe("DemoBadge layout at large text", () => {
  it("has no fixed size, one line, capped scale, remounts on fontScale", () => {
    let tree!: TestRenderer.ReactTestRenderer;
    act(() => { tree = TestRenderer.create(<DemoBadge server={DEMO_SERVER} />); });
    const box = tree.root.findByType("view" as never).props.style;
    expect(box.width).toBeUndefined();
    expect(box.height).toBeUndefined();
    expect(box.flexShrink).toBe(0);
    const text = tree.root.findByType("text" as never);
    expect(text.props.numberOfLines).toBe(1);
    expect(text.props.maxFontSizeMultiplier).toBeLessThanOrEqual(1.3);
    expect((text as unknown as { _fiber: { key: string } })._fiber.key).toBe("2");
  });
});

describe("withDemoPrefix", () => {
  const { withDemoPrefix } = require("../src/DemoBadge");
  it("prefixes once", () => {
    expect(withDemoPrefix("DigitVA")).toBe("DEMO - DigitVA");
    expect(withDemoPrefix("DEMO - DigitVA")).toBe("DEMO - DigitVA");
  });
});
