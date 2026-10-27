import React from "react";
import TestRenderer, { act } from "react-test-renderer";

jest.mock("react-native", () => ({ Platform: { OS: "android" }, Text: "text", View: "view" }));
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

describe("withDemoPrefix", () => {
  const { withDemoPrefix } = require("../src/DemoBadge");
  it("prefixes once", () => {
    expect(withDemoPrefix("DigitVA")).toBe("DEMO - DigitVA");
    expect(withDemoPrefix("DEMO - DigitVA")).toBe("DEMO - DigitVA");
  });
});
