import { canFollowUpDeath, canStartDeathInterview, deathPhoneUrl } from "../src/deathWorkflow";

it("offers interview actions only in known startable states", () => {
  expect(canStartDeathInterview("registered")).toBe(true);
  expect(canStartDeathInterview("refused")).toBe(true);
  expect(canStartDeathInterview("in_progress")).toBe(true);
  for (const state of ["submitted", "cancelled", "duplicate", "unknown"]) {
    expect(canStartDeathInterview(state)).toBe(false);
  }
});

it("limits follow-up actions to states that allow contact and visits", () => {
  expect(canFollowUpDeath("scheduled")).toBe(true);
  expect(canFollowUpDeath("paused")).toBe(true);
  expect(canFollowUpDeath("refused")).toBe(false);
  expect(canFollowUpDeath("submitted")).toBe(false);
});

it("never turns a masked or malformed phone into a dialler link", () => {
  expect(deathPhoneUrl("+91 98765 43210")).toBe("tel:+919876543210");
  expect(deathPhoneUrl("******3210")).toBeUndefined();
  expect(deathPhoneUrl("javascript:alert(1)")).toBeUndefined();
  expect(deathPhoneUrl(undefined)).toBeUndefined();
});
