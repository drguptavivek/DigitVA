import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/theme", () => ({ useTheme: () => ({ colors: { background: "#131E2E", accent: "#78A9FF", textMuted: "#B5C2D1" } }) }));
jest.mock("../src/web/common", () => ({
  WebShell: ({ children }: { children: React.ReactNode }) => require("react").createElement("web-shell", null, children),
}));
jest.mock("../src/ui", () => ({
  useUiStyles: () => ({ card: {}, text: {} }),
  errorReference: () => "Ref: test",
  Button: (props: object) => require("react").createElement("button", props),
}));

import { DeferredScreen } from "../src/web/LazyInterviewScreen";

test("pending route downloads keep a themed shell and visible loading status", async () => {
  let finish!: (value: { default: React.ComponentType }) => void;
  const load = () => new Promise<{ default: React.ComponentType }>((resolve) => { finish = resolve; });
  let renderer!: ReactTestRenderer;
  await act(async () => { renderer = create(<DeferredScreen load={load} />); });
  expect(renderer.root.findAllByType("web-shell" as never)).toHaveLength(1);
  const loading = renderer.root.findAll((node) => node.type === "View" as never && node.props.testID === "web-route-loading")[0];
  expect(loading.props.style.backgroundColor).toBe("#131E2E");
  expect(loading.props.accessibilityLabel).toBe("loading");
  expect(JSON.stringify(renderer.toJSON())).toContain("loading");
  await act(async () => { finish({ default: () => React.createElement("interview-ready") }); });
  expect(renderer.root.findAllByType("interview-ready" as never)).toHaveLength(1);
  await act(async () => { renderer.unmount(); });
});

test("interview downloads only on use and a failed download can retry without page reload", async () => {
  const load = jest.fn()
    .mockRejectedValueOnce(new TypeError("Failed to fetch dynamically imported module"))
    .mockResolvedValue({ default: () => React.createElement("interview-ready") });
  expect(load).not.toHaveBeenCalled();
  const errors = jest.spyOn(console, "error").mockImplementation(() => undefined);
  let renderer!: ReactTestRenderer;
  try {
    await act(async () => { renderer = create(<DeferredScreen load={load} />); });
    expect(load).toHaveBeenCalledTimes(1);
    expect(JSON.stringify(renderer.toJSON())).toContain("errNetwork");
    const retry = renderer.root.findByType("button" as never);
    await act(async () => { retry.props.onPress(); });
    expect(load).toHaveBeenCalledTimes(2);
    expect(renderer.root.findAllByType("interview-ready" as never)).toHaveLength(1);
  } finally {
    await act(async () => { renderer?.unmount(); });
    errors.mockRestore();
  }
});

test("a screen whose code already downloaded remounts without the loading fallback", async () => {
  const load = jest.fn().mockResolvedValue({ default: () => React.createElement("deaths-ready") });
  let first!: ReactTestRenderer;
  await act(async () => { first = create(<DeferredScreen load={load} />); });
  expect(first.root.findAllByType("deaths-ready" as never)).toHaveLength(1);
  await act(async () => { first.unmount(); });
  // A sidebar revisit mounts a new instance: the first committed render already shows the screen.
  let again!: ReactTestRenderer;
  act(() => { again = create(<DeferredScreen load={load} />); });
  expect(again.root.findAllByType("deaths-ready" as never)).toHaveLength(1);
  expect(again.root.findAll((node) => node.props?.testID === "web-route-loading")).toHaveLength(0);
  expect(load).toHaveBeenCalledTimes(1);
  await act(async () => { again.unmount(); });
});

test("a render bug in the screen is not reported as a connection problem", async () => {
  const load = jest.fn().mockResolvedValue({ default: () => { throw new TypeError("Cannot read properties of undefined (reading 'x')"); } });
  const errors = jest.spyOn(console, "error").mockImplementation(() => undefined);
  let renderer!: ReactTestRenderer;
  try {
    await act(async () => { renderer = create(<DeferredScreen load={load} />); });
    const out = JSON.stringify(renderer.toJSON());
    expect(out).toContain("errGeneric");
    expect(out).not.toContain("errNetwork");
  } finally {
    await act(async () => { renderer?.unmount(); });
    errors.mockRestore();
  }
});
