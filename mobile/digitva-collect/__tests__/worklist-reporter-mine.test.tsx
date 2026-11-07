import React from "react";
import { act, create } from "react-test-renderer";

let mockAccount: Record<string, unknown>;
const mockRegistered = jest.fn((_props: unknown) => null);
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => ({ userId: "u1" }),
  useRouter: () => ({ push: jest.fn(), replace: jest.fn(), back: jest.fn() }),
  useFocusEffect: jest.fn(),
}));
jest.mock("../src/AppState", () => ({ useAppState: () => ({ accounts: [mockAccount] }) }));
jest.mock("../src/nativeRoutes/RegisteredDeaths", () => ({ __esModule: true, default: (props: unknown) => mockRegistered(props) }));

import Worklist from "../src/nativeRoutes/worklist";

it("a reporter whose interview access is closed still asks for their own list (registered=mine)", async () => {
  mockAccount = { user_id: "u1", collection_access: false, registration_access: true, registered_deaths_access: true };
  await act(async () => { create(<Worklist />); });
  expect(mockRegistered).toHaveBeenCalledWith(expect.objectContaining({ userId: "u1", registeredMine: true }));
});
