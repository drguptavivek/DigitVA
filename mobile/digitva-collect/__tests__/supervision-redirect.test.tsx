import React from "react";
import { Platform } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({ Redirect: ({ href }: { href: unknown }) => <div data-href={JSON.stringify(href)} /> }));
jest.mock("../src/nativeRouteScreens", () => ({ Supervision: () => <section data-native="supervision" /> }));

import SupervisionRoute from "../app/supervision";

function target() {
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(<SupervisionRoute />); });
  return JSON.parse(tree.root.findByType("div").props["data-href"]);
}

describe("/supervision route", () => {
  const original = Platform.OS;
  afterEach(() => { Platform.OS = original; });

  it("redirects old links to the Deaths tab's supervision preset", () => {
    Platform.OS = "web";
    expect(target()).toEqual({ pathname: "/death-registration", params: { view: "mine", preset: "supervision" } });
  });

  it("shows the supervision screen on the phone", () => {
    Platform.OS = "ios";
    let tree!: ReturnType<typeof create>;
    act(() => { tree = create(<SupervisionRoute />); });
    expect(tree.root.findByType("section").props["data-native"]).toBe("supervision");
  });
});
