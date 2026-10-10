import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "date-picker-modal.spec.ts",
  timeout: 30_000,
  use: { ...devices["Desktop Chrome"] },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]
});
