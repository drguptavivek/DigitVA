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

import CodingRoute from "../app/coding";
import ReviewingRoute from "../app/reviewing";
import WorkspaceRoute from "../app/workspace";
import * as NativeScreens from "../src/nativeRouteScreens.native";

test("native coding, reviewing and workspace routes all explain that coding is on the web", () => {
  expect(NativeScreens.CodingOnWeb).toBeDefined();
  expect(NativeScreens.Coding).toBe(NativeScreens.CodingOnWeb);
  expect(NativeScreens.Reviewing).toBe(NativeScreens.CodingOnWeb);
  expect(NativeScreens.Workspace).toBe(NativeScreens.CodingOnWeb);
  expect(CodingRoute).toBe(NativeScreens.CodingOnWeb);
  expect(ReviewingRoute).toBe(NativeScreens.CodingOnWeb);
  expect(typeof WorkspaceRoute).toBe("function");
});
