import { platformLabel } from "../src/platformLabel";

test("known platforms get display names, others pass through", () => {
  expect([platformLabel("ios"), platformLabel("android"), platformLabel("web"), platformLabel(null)]).toEqual(["iOS", "Android", "web", ""]);
});
