import React from "react";
import { act, create } from "react-test-renderer";

let mockParams: Record<string, string> = {};
jest.mock("expo-router", () => ({ useLocalSearchParams: () => mockParams }));
jest.mock("../src/nativeRoutes/register", () => ({ __esModule: true, default: () => <div data-screen="interviewer" /> }));
jest.mock("../src/nativeRoutes/supervisorDeathEdit", () => ({ __esModule: true, SUPERVISOR_EDIT: "supervisor", default: () => <div data-screen="supervisor" /> }));

import RegisterRoute from "../src/nativeRoutes/registerRoute";

const screen = () => {
  let tree!: ReturnType<typeof create>;
  act(() => { tree = create(<RegisterRoute />); });
  return tree.root.findByType("div").props["data-screen"];
};

it("opens the interviewer's form unless the route is in supervisor mode", () => {
  mockParams = { userId: "u" };
  expect(screen()).toBe("interviewer");
  mockParams = { userId: "u", deathId: "D1", by: "supervisor" };
  expect(screen()).toBe("supervisor");
});
