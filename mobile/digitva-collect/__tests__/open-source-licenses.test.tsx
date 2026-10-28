import React from "react";
import { Linking, Text } from "react-native";
import TestRenderer, { act } from "react-test-renderer";

import OpenSourceLicenses, { WHO_ICD11_CONTENT_LICENSE_URL, WHO_ICD11_SOFTWARE_TERMS_URL } from "../src/nativeRoutes/openSourceLicenses";
import { DIGITVA_MIT_NOTICE, SMARTVA_MIT_NOTICE, WHO_VA_NOTICE } from "../src/openSourceLicenses";
import { setUiLocale } from "../src/i18n";

jest.mock("../src/ui", () => ({
  Screen: ({ title, children }: { title: string; children: React.ReactNode }) => {
    const mockReact = require("react");
    const mockRN = require("react-native");
    return mockReact.createElement(mockRN.View, null, mockReact.createElement(mockRN.Text, null, title), children);
  },
  Button: ({ label, onPress }: { label: string; onPress: () => void }) => {
    const mockReact = require("react");
    const mockRN = require("react-native");
    return mockReact.createElement(mockRN.Pressable, { onPress }, mockReact.createElement(mockRN.Text, null, label));
  },
  useUiStyles: () => ({ headline: {}, muted: {}, text: {}, error: {} }),
}));

describe("Open-source licenses and notices screen", () => {
  afterEach(() => setUiLocale("en"));

  it("shows the complete bundled MIT notices and distinguishes WHO classification from software terms", () => {
    let tree!: TestRenderer.ReactTestRenderer;
    act(() => { tree = TestRenderer.create(<OpenSourceLicenses />); });
    const text = tree.root.findAllByType(Text).map((node) => node.props.children).join("\n");

    expect(text).toContain("DigitVA");
    expect(text).toContain("SmartVA Analyze");
    expect(text).toContain("International Classification of Diseases, Eleventh Revision (ICD-11)");
    expect(text).toContain("separate terms");
    expect(text).toContain("does not claim WHO endorsement");
    expect(text).toContain(DIGITVA_MIT_NOTICE);
    expect(text).toContain(SMARTVA_MIT_NOTICE);
    expect(text).toContain(WHO_VA_NOTICE);
    expect(text).toContain("Hindi questionnaire version 6");
    expect(text).toContain("review and redistribution clearance remain pending");
    expect(text).toContain("Open-source licenses and notices");
  });

  it("opens each official WHO licence only after the user taps its link", async () => {
    const openURL = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    let tree!: TestRenderer.ReactTestRenderer;
    act(() => { tree = TestRenderer.create(<OpenSourceLicenses />); });
    expect(openURL).not.toHaveBeenCalled();

    const buttons = tree.root.findAll((node) => typeof node.props.onPress === "function");
    const buttonFor = (label: string) => buttons.find((node) =>
      node.findAllByType(Text).some((child) => child.props.children === label),
    );
    await act(async () => {
      buttonFor("View CC BY-ND 3.0 IGO terms")?.props.onPress();
    });
    expect(openURL).toHaveBeenLastCalledWith(WHO_ICD11_CONTENT_LICENSE_URL);
    await act(async () => {
      buttonFor("View WHO ICD-11 software license terms")?.props.onPress();
    });
    expect(openURL).toHaveBeenCalledWith(WHO_ICD11_SOFTWARE_TERMS_URL);
    openURL.mockRestore();
  });

  it("expands the locally bundled package and Rust notices without opening a network link", async () => {
    const openURL = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    let tree!: TestRenderer.ReactTestRenderer;
    act(() => { tree = TestRenderer.create(<OpenSourceLicenses />); });
    expect(tree.root.findAllByType(Text).map((node) => node.props.children).join("\n")).not.toContain("PACKAGE INVENTORY");
    const button = tree.root.findAll((node) => typeof node.props.onPress === "function").find((node) =>
      node.findAllByType(Text).some((child) => child.props.children === "View third-party software notices"),
    );
    await act(async () => { button?.props.onPress(); });
    const text = tree.root.findAllByType(Text).map((node) => node.props.children).join("\n");
    expect(text).toContain("Android-compatible non-development npm lockfile packages");
    expect(text).toContain("smartva-rust@3.0.2");
    expect(text).toContain("NOTICE TEXT NOT FOUND LOCALLY");
    expect(text).toContain("@react-native/codegen");
    expect(openURL).not.toHaveBeenCalled();
    openURL.mockRestore();
  });

  it("translates app copy into Hindi and keeps the legal notices intact", () => {
    setUiLocale("hi");
    let tree!: TestRenderer.ReactTestRenderer;
    act(() => { tree = TestRenderer.create(<OpenSourceLicenses />); });
    const text = tree.root.findAllByType(Text).map((node) => node.props.children).join("\n");
    expect(text).toContain("ओपन-सोर्स लाइसेंस और सूचनाएँ");
    expect(text).toContain("WHO ICD-11 वर्गीकरण");
    expect(text).toContain(DIGITVA_MIT_NOTICE);
    expect(text).toContain(SMARTVA_MIT_NOTICE);
    expect(text).toContain(WHO_VA_NOTICE);
    expect(text).toContain("CC BY-ND 3.0 IGO की शर्तें देखें");
  });
});
