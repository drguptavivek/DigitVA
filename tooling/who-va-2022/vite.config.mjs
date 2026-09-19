// Vite config for the questionnaire front end.
//
//   dev  — `npm run dev` serves entry.mjs with HMR on 5174; nginx in the
//          vaform container proxies /static/vendor/who-va-2022/ to it.
//   prod — `npm run build:web` emits the same entry to dist/, which nginx
//          serves directly from /srv/vaform.
//
// The committed esbuild bundle (build.mjs) stays as the no-Node fallback;
// see decision W2 in docs/planning/who-va-2022-web-intake-plan.md.
import { defineConfig } from "vite";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.resolve(here, "..", "..");
const vendorSrc = path.join(repo, "vendor", "who-va-2022", "src");

// Served under the same public path as the committed bundle so the intake
// page's <script src> is identical in both modes.
const PUBLIC_PATH = "/static/vendor/who-va-2022/";

export default defineConfig({
  root: here,
  base: PUBLIC_PATH,
  resolve: {
    alias: { "@digitva/who-va-2022": vendorSrc },
  },
  define: { __DEV__: JSON.stringify(process.env.NODE_ENV !== "production") },
  server: {
    host: "0.0.0.0",
    port: 5174,
    strictPort: true,
    // The browser reaches Vite through nginx on the container's published
    // port, so HMR must advertise that path rather than 5174 directly.
    hmr: { path: `${PUBLIC_PATH}@vite/hmr`, clientPort: Number(process.env.VAFORM_PUBLIC_PORT ?? 8080) },
    // vendor/ and tooling/ are bind-mounted in dev; poll so edits made on the
    // host are seen inside the container on every platform.
    watch: { usePolling: true, interval: 300 },
    fs: { allow: [repo] },
  },
  build: {
    outDir: path.join(here, "dist"),
    emptyOutDir: true,
    target: "es2020",
    sourcemap: false,
    rollupOptions: {
      input: path.join(here, "entry.mjs"),
      output: {
        entryFileNames: "who-va-2022.web-component.js",
        chunkFileNames: "who-va-2022.[hash].js",
        assetFileNames: "who-va-2022.[hash][extname]",
      },
    },
  },
});
