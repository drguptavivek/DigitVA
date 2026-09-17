import { defineConfig } from "tsup";

export default defineConfig({
  entry: {
    index: "src/index.ts",
    native: "src/native.tsx",
    web: "src/web.tsx",
    "web-component": "src/web-component.tsx"
  },
  format: ["esm"],
  dts: true,
  sourcemap: true,
  clean: true,
  splitting: true,
  external: ["react", "react-dom", "react-native", "react-native-web"]
});
