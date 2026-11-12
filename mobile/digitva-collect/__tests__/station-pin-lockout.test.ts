import { ApiError } from "../src/api";
import { pinFailureText } from "../src/web/StationRosterScreen";

jest.mock("../src/ui/controls", () => ({ CheckMark: "span", Checkbox: "span" }));

it("shows the wait after five wrong PINs and never says data was erased", () => {
  const text = pinFailureText(
    new ApiError(429, "pin_locked_out", undefined, undefined, { retry_after_secs: 90 }),
    "stationPinUnlockFailed",
  );
  expect(text).toBe("Too many wrong PINs. Try again in 2 min.");
  expect(text).not.toMatch(/wipe|erase/i);
});

it("shows the tries left on a 401, and the plain failure otherwise", () => {
  expect(
    pinFailureText(new ApiError(401, "bad_pin", undefined, undefined, { remaining_attempts: 3 }), "stationPinUnlockFailed"),
  ).toBe("Wrong PIN. 3 tries left before a wait.");
  expect(pinFailureText(new Error("x"), "stationStoreUnlockFailed")).toBe("Could not unlock the roster user's store.");
});
