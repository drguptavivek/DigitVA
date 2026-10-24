jest.mock("../src/nativeRoutes/case", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/enrol", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/form", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/index", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/pin-setup", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/register", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/sign-in", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/unlock", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/worklist", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/revision", () => ({ __esModule: true, default: () => null }));
jest.mock("../src/nativeRoutes/plusWorkspace", () => ({
  __esModule: true,
  PlusCoding: () => null,
  PlusReviewing: () => null,
  PlusWorkspace: () => null,
}));

import CodingRoute from "../app/coding";
import ReviewingRoute from "../app/reviewing";
import WorkspaceRoute from "../app/workspace";
import * as NativeScreens from "../src/nativeRouteScreens.native";
import { isPlusVariant } from "../src/appVariant";

test("plain build: native coding, reviewing and workspace routes all explain that coding is on the web", () => {
  expect(NativeScreens.CodingOnWeb).toBeDefined();
  expect(NativeScreens.Coding).toBe(NativeScreens.CodingOnWeb);
  expect(NativeScreens.Reviewing).toBe(NativeScreens.CodingOnWeb);
  expect(NativeScreens.Workspace).toBe(NativeScreens.CodingOnWeb);
  expect(CodingRoute).toBe(NativeScreens.CodingOnWeb);
  expect(ReviewingRoute).toBe(NativeScreens.CodingOnWeb);
  expect(typeof WorkspaceRoute).toBe("function");
});

test("variant detection reads extra.appVariant", () => {
  expect(isPlusVariant({ appVariant: "plus" })).toBe(true);
  expect(isPlusVariant({})).toBe(false);
  expect(isPlusVariant({ appVariant: "development" })).toBe(false);
  expect(isPlusVariant(undefined)).toBe(false);
});

describe("Collect Plus build", () => {
  function load() {
    let screens!: typeof NativeScreens;
    let plusScreens!: typeof import("../src/nativeRoutes/plusWorkspace");
    jest.isolateModules(() => {
      jest.doMock("expo-constants", () => ({ __esModule: true, default: { expoConfig: { extra: { appVariant: "plus" } } } }));
      screens = require("../src/nativeRouteScreens.native");
      plusScreens = require("../src/nativeRoutes/plusWorkspace");
    });
    return { screens, plusScreens };
  }

  test("native coding, reviewing and workspace routes render the real screens", () => {
    const { screens, plusScreens } = load();
    expect(screens.Coding).toBe(plusScreens.PlusCoding);
    expect(screens.Reviewing).toBe(plusScreens.PlusReviewing);
    expect(screens.Workspace).toBe(plusScreens.PlusWorkspace);
    expect(screens.Coding).not.toBe(screens.CodingOnWeb);
  });
});
