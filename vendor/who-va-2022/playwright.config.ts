import { defineConfig, devices } from "@playwright/test";

const slowMo = Number(process.env.E2E_SLOW_MO ?? 0);

export default defineConfig({
  testDir: "./e2e",
  outputDir: "test-results/e2e",
  timeout: slowMo > 0 ? 180_000 : 30_000,
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:5173",
    launchOptions: { slowMo },
    screenshot: "only-on-failure",
    trace: "on",
    video: "on"
  },
  webServer: {
    command: "pnpm exec vite demo --host 127.0.0.1 --port 5173",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }]
});
