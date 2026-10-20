import React from "react";
import { Linking, Platform } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string, vars?: Record<string, unknown>) => (vars ? `${key}:${JSON.stringify(vars)}` : key) }));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled, loading }: { label: string; onPress: () => void; disabled?: boolean; loading?: boolean }) =>
    <button data-label={label} data-disabled={Boolean(disabled)} data-loading={Boolean(loading)} onClick={onPress} />,
  useUiStyles: () => ({ text: {}, muted: {}, error: {}, row: {} })
}));

import { directionsUrl, LocationCapture, MapsLink, MapsPinButton, mapsUrl, type GpsFix } from "../src/web/LocationCapture";

type Success = (position: { coords: { latitude: number; longitude: number; accuracy: number } }) => void;
type Failure = (error: { code: number }) => void;

function fakeLocator() {
  const calls: Array<{ ok: Success; fail: Failure; options: unknown }> = [];
  return { calls, getCurrentPosition: jest.fn((ok: Success, fail: Failure, options: unknown) => { calls.push({ ok, fail, options }); }) };
}

const button = (tree: ReturnType<typeof create>, label: string) => tree.root.findAllByProps({ "data-label": label });
const text = (tree: ReturnType<typeof create>) => JSON.stringify(tree.toJSON());

describe("LocationCapture", () => {
  beforeEach(() => { jest.replaceProperty(Platform, "OS", "web"); });
  afterEach(() => { jest.restoreAllMocks(); });

  it("never reads the position until the button is pressed, then reads once with the owner's options", async () => {
    const locator = fakeLocator();
    const onChange = jest.fn();
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<LocationCapture value={null} onChange={onChange} geolocation={locator} />); });
    expect(locator.getCurrentPosition).not.toHaveBeenCalled();
    await act(async () => button(tree, "locationCapture")[0].props.onClick());
    expect(locator.getCurrentPosition).toHaveBeenCalledTimes(1);
    expect(locator.calls[0].options).toEqual({ enableHighAccuracy: true, timeout: 20000, maximumAge: 0 });
    // Capturing: the button is disabled and spinning.
    const busy = button(tree, "locationCapturing")[0];
    expect([busy.props["data-disabled"], busy.props["data-loading"]]).toEqual([true, true]);
    await act(async () => locator.calls[0].ok({ coords: { latitude: 28.5, longitude: 77.2, accuracy: 12.4 } }));
    expect(onChange).toHaveBeenCalledWith({ latitude: 28.5, longitude: 77.2, accuracy_m: 12.4 });
  });

  it("shows the captured accuracy with Retake and Clear, and Clear empties the value", async () => {
    const fix: GpsFix = { latitude: 28.5, longitude: 77.2, accuracy_m: 12.4 };
    const locator = fakeLocator();
    const onChange = jest.fn();
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<LocationCapture value={fix} onChange={onChange} geolocation={locator} />); });
    expect(text(tree)).toContain('locationCaptured:{\\"meters\\":12}');
    await act(async () => button(tree, "locationRetake")[0].props.onClick());
    expect(locator.getCurrentPosition).toHaveBeenCalledTimes(1);
    await act(async () => locator.calls[0].ok({ coords: { latitude: 1, longitude: 2, accuracy: 3 } }));
    expect(onChange).toHaveBeenLastCalledWith({ latitude: 1, longitude: 2, accuracy_m: 3 });
    await act(async () => button(tree, "locationClear")[0].props.onClick());
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it.each([[1, "locationDenied"], [2, "locationUnavailable"], [3, "locationTimeout"]])(
    "reports error code %i as a short message and leaves the value alone",
    async (code, message) => {
      const locator = fakeLocator();
      const onChange = jest.fn();
      let tree!: ReturnType<typeof create>;
      await act(async () => { tree = create(<LocationCapture value={null} onChange={onChange} geolocation={locator} />); });
      await act(async () => button(tree, "locationCapture")[0].props.onClick());
      await act(async () => locator.calls[0].fail({ code }));
      expect(text(tree)).toContain(message);
      expect(onChange).not.toHaveBeenCalled();
      // Try again is possible.
      expect(button(tree, "locationCapture")).toHaveLength(1);
    }
  );

  it("renders nothing on native or when the browser has no geolocation", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<LocationCapture value={null} onChange={jest.fn()} geolocation={fakeLocator()} />); });
    expect(tree.toJSON()).not.toBeNull();
    jest.replaceProperty(Platform, "OS", "ios");
    await act(async () => { tree = create(<LocationCapture value={null} onChange={jest.fn()} geolocation={fakeLocator()} />); });
    expect(tree.toJSON()).toBeNull();
    jest.replaceProperty(Platform, "OS", "web");
    await act(async () => { tree = create(<LocationCapture value={null} onChange={jest.fn()} />); });
    expect(tree.toJSON()).toBeNull();
  });
});

describe("MapsLink", () => {
  beforeEach(() => { jest.replaceProperty(Platform, "OS", "web"); });
  afterEach(() => { jest.restoreAllMocks(); });

  it("links to Google Maps in a new tab with rel noopener noreferrer, only when coordinates exist", async () => {
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<MapsLink latitude={28.613939} longitude={77.209021} />); });
    const anchor = tree.root.findByType("a");
    expect(anchor.props).toMatchObject({
      href: "https://www.google.com/maps/search/?api=1&query=28.613939,77.209021",
      target: "_blank",
      rel: "noopener noreferrer"
    });
    expect(text(tree)).toContain("28.613939, 77.209021");
    expect(mapsUrl(1, -2)).toBe("https://www.google.com/maps/search/?api=1&query=1,-2");
    for (const props of [{}, { latitude: null, longitude: null }, { latitude: 1 }, { latitude: Number.NaN, longitude: 2 }]) {
      await act(async () => { tree = create(<MapsLink {...props} />); });
      expect(tree.toJSON()).toBeNull();
    }
  });
});

describe("MapsPinButton", () => {
  afterEach(() => { jest.restoreAllMocks(); });

  it("builds directions per platform from the numbers alone", () => {
    expect(directionsUrl(12.97, -77.5, "web")).toBe("https://www.google.com/maps/dir/?api=1&destination=12.97,-77.5");
    expect(directionsUrl(12.97, -77.5, "ios")).toBe("maps://?daddr=12.97,-77.5");
    expect(directionsUrl(12.97, -77.5, "android")).toBe("geo:12.97,-77.5?q=12.97,-77.5");
  });

  it("is a named 44px link to Google Maps directions in a new tab on the web, only with a fix", async () => {
    jest.replaceProperty(Platform, "OS", "web");
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<MapsPinButton latitude={12.97} longitude={77.59} />); });
    const link = tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "case-maps-link")[0];
    expect(link.props).toMatchObject({
      accessibilityRole: "link",
      accessibilityLabel: "openInMaps",
      href: "https://www.google.com/maps/dir/?api=1&destination=12.97,77.59",
      hrefAttrs: { target: "_blank", rel: "noopener noreferrer" },
    });
    const style = Object.assign({}, ...[link.props.style].flat(3).filter(Boolean));
    expect([style.minWidth, style.minHeight]).toEqual([44, 44]);
    for (const props of [{}, { latitude: null, longitude: null }, { latitude: 1 }, { latitude: Number.NaN, longitude: 2 }]) {
      await act(async () => { tree = create(<MapsPinButton {...props} />); });
      expect(tree.toJSON()).toBeNull();
    }
  });

  it("hands the platform maps URL to Linking on a phone", async () => {
    jest.replaceProperty(Platform, "OS", "android");
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true);
    let tree!: ReturnType<typeof create>;
    await act(async () => { tree = create(<MapsPinButton latitude={12.97} longitude={77.59} />); });
    const link = tree.root.findAll((n) => typeof n.type === "string" && n.props.testID === "case-maps-link")[0];
    expect(link.props.href).toBeUndefined();
    const pressable = tree.root.findAll((n) => n.props.testID === "case-maps-link" && typeof n.props.onPress === "function")[0];
    await act(async () => pressable.props.onPress());
    expect(open).toHaveBeenCalledWith("geo:12.97,77.59?q=12.97,77.59");
  });
});
