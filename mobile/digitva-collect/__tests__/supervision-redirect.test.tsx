import React from "react";
import { Platform } from "react-native";
import { act, create } from "react-test-renderer";

jest.mock("expo-router", () => ({ Redirect: ({ href }: { href: unknown }) => <div data-href={JSON.stringify(href)} /> }));

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

  it("sends a native build to the worklist, as before", () => {
    Platform.OS = "ios";
    expect(target()).toBe("/worklist");
  });
});
