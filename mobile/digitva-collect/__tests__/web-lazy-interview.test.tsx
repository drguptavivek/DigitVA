import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

jest.mock("../src/i18n", () => ({ t: (key: string) => key }));
jest.mock("../src/ui", () => ({
  useUiStyles: () => ({ card: {}, text: {} }),
  Button: (props: object) => require("react").createElement("button", props),
}));

import { DeferredScreen } from "../src/web/LazyInterviewScreen";

test("interview downloads only on use and a failed download can retry without page reload", async () => {
  const load = jest.fn()
    .mockRejectedValueOnce(new TypeError("offline chunk"))
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
