import { expect, it } from "vitest";
import { ENGINE_VERSION as coreEngineVersion } from "../src/core.js";
import { ENGINE_VERSION } from "../src/index.js";

it("exports the runtime contract version from the public entries", () => {
  expect(ENGINE_VERSION).toBe(1);
  expect(coreEngineVersion).toBe(ENGINE_VERSION);
});
