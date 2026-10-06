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
jest.mock("../src/nativeRoutes/workspaceScreens", () => ({
  CodingScreen: () => null,
  ReviewingScreen: () => null,
  WorkspaceScreen: () => null,
}));

import CodingRoute from "../app/coding";
import ReviewingRoute from "../app/reviewing";
import WorkspaceRoute from "../app/workspace";
import * as NativeScreens from "../src/nativeRouteScreens.native";

test("native router exposes coding, reviewing, and workspace screens", () => {
  expect(NativeScreens.Coding).toBeDefined();
  expect(NativeScreens.Reviewing).toBeDefined();
  expect(NativeScreens.Workspace).toBeDefined();
  expect(CodingRoute).toBe(NativeScreens.Coding);
  expect(ReviewingRoute).toBe(NativeScreens.Reviewing);
  expect(typeof WorkspaceRoute).toBe("function");
});
