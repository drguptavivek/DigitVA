// Web checks that Maestro cannot make: the supervision view exists only in the browser app.
// Run through ../run-web-supervisor.sh. No trace, video or screenshot: they would record
// the typed password.
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: ".",
  testMatch: "*.spec.ts",
  outputDir: "/tmp/digitva-e2e-web",
  timeout: 90_000,
  reporter: "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8051",
    // The installed system Chrome: the browsers Playwright downloads may not match this version.
    channel: "chrome",
    trace: "off",
    video: "off",
    screenshot: "off"
  }
});
