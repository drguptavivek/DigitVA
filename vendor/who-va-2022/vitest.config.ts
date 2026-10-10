import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: { "react-native": "react-native-web" },
    conditions: ["browser", "module", "import", "development"],
    mainFields: ["browser", "module", "main"],
    extensions: [
      ".web.mjs",
      ".web.js",
      ".web.ts",
      ".web.tsx",
      ".mjs",
      ".js",
      ".mts",
      ".ts",
      ".jsx",
      ".tsx",
      ".json"
    ]
  },
  test: {
    exclude: [...configDefaults.exclude, "e2e/**"]
  }
});
