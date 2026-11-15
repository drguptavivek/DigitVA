import { expect, test } from "@playwright/test";

// E2E happy path: the supervisor sees the case the interviewer sent in this run, past Registered.
// Needs the Maestro run's users (70-interview-send has sent E2E<run>regA).
const { E2E_SUPERVISOR_EMAIL, E2E_PASSWORD, E2E_RUN_ID } = process.env;

test("supervisor sees the case the interviewer sent", async ({ page }) => {
  test.skip(!E2E_SUPERVISOR_EMAIL || !E2E_PASSWORD || !E2E_RUN_ID, "needs E2E_SUPERVISOR_EMAIL, E2E_PASSWORD, E2E_RUN_ID");

  await page.goto("/vaauth/valogin");
  await page.locator("#login-email-form input[name=email]").fill(E2E_SUPERVISOR_EMAIL!);
  // The submit button stays disabled until the proof-of-work CAPTCHA is solved; click waits for it.
  await page.locator("#login-email-form input[type=submit], #login-email-form button[type=submit]").click();
  await page.locator("input[type=password]").fill(E2E_PASSWORD!);
  await page.locator("form input[type=submit], form button[type=submit]").click();

  await page.goto("/death-registration?view=mine&preset=supervision");
  // The default tile lists only cases needing a decision; Total in scope lists every supervised case.
  await page.getByRole("button", { name: /^Total in scope/ }).click();
  // Sent, not just registered: the case's own row no longer reads "Registered" (state_registered);
  // after sending it may already show a later stage (Submitted, coding), so match by exclusion.
  // The status follows the name; every row also says "Registered by ...", so test only the status.
  const name = `E2E${E2E_RUN_ID}regA`;
  await expect(page.getByText(name).first()).toBeVisible({ timeout: 30_000 });
  // Rows are plain divs and text nodes are not space-separated, so: the smallest element holding the
  // name and the row's case id (SC01-000123) must not carry a not-yet-sent status. "Registered by" is
  // on every row; only a bare "Registered" status counts.
  const sent = page.locator("div").filter({ hasText: name }).filter({ hasText: /SC\d+-\d+/ })
    .filter({ hasNotText: /In progress|Cancelled|Registered(?! by)/ });
  await expect(sent.last()).toBeVisible({ timeout: 30_000 });
});
