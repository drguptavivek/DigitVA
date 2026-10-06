import { ApiError } from "../src/api";

const mockRefresh = jest.fn();
const mockRequest = jest.fn();
jest.mock("../src/auth", () => ({
  authedRequest: (...args: unknown[]) => mockRequest(...args),
  refreshAccessSummaryForAction: (...args: unknown[]) => mockRefresh(...args),
}));

import { getDeathRegistrationAccess, getNativeRegisteredDeaths, getNativeRegistrationCase, patchNativeDeathRegistration } from "../src/deathRegistrationApi";

beforeEach(() => {
  mockRefresh.mockReset();
  mockRequest.mockReset();
});

it("allows cached interviewer registration targets only after an actual offline transport failure", async () => {
  mockRefresh.mockRejectedValue(new TypeError("Network request failed"));
  await expect(getDeathRegistrationAccess("u1")).resolves.toBeUndefined();
  expect(mockRefresh).toHaveBeenCalledWith("u1");
});

it.each([
  new ApiError(401, "unauthorized"),
  new ApiError(403, "no_collection_access"),
  new ApiError(200, "malformed_response"),
])("keeps authorization failures closed rather than enabling cached targets", async (error) => {
  mockRefresh.mockRejectedValue(error);
  await expect(getDeathRegistrationAccess("u1")).rejects.toBe(error);
});

it("PATCHes only changed registration fields and preserves a blank clear with the seen timestamp", async () => {
  mockRequest.mockResolvedValue({ body: { case: {
    death_id: "d1", project_id: "P1", site_id: "S1", state: "registered", updated_at: "2026-10-06T12:00:00+00:00",
    deceased: {}, household_address: {}, informant: {}, links: { update: "/api/v1/intake/deaths/d1" },
  } } });
  await patchNativeDeathRegistration("u1", "d1", { address: "", deceased_sex: "female" }, "2026-10-06T11:00:00+00:00");
  expect(mockRequest).toHaveBeenCalledWith("u1", "/api/v1/intake/deaths/d1", {
    method: "PATCH",
    body: { address: "", deceased_sex: "female", if_updated_at: "2026-10-06T11:00:00+00:00" },
  });
});

it("loads reporter edits from the bounded own-registration list, not a forbidden case detail", async () => {
  mockRequest.mockResolvedValue({ body: { deaths: [], next_cursor: null } });
  await getNativeRegisteredDeaths("u1", true, "cursor-1");
  expect(mockRequest).toHaveBeenCalledWith("u1", "/api/v1/intake/deaths?limit=50&registered=mine&cursor=cursor-1");
  expect(mockRequest.mock.calls[0][1]).not.toContain("/cases/");
});

it("rejects malformed detail age data before the form consumes it", async () => {
  mockRequest.mockResolvedValue({ body: { case: {
    death_id: "d1", project_id: "P1", site_id: "S1", state: "registered", updated_at: "2026-10-06T12:00:00+00:00",
    deceased: { age_years: Number.NaN }, household_address: {}, informant: {}, links: { update: "/api/v1/intake/deaths/d1" },
  } } });
  await expect(getNativeRegistrationCase("u1", "d1")).rejects.toMatchObject({ code: "malformed_response" });
});
