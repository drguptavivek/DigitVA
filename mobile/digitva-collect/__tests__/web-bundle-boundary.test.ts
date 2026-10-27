import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

// Static-import walk from every Expo Router route (require.context includes all of app/),
// resolving relative imports the way Metro does for web (.web beats plain). Fails when the
// native-only SQLite store is reachable: `make check-web` then dies on the wa-sqlite wasm.
const root = resolve(__dirname, "..");
const FORBIDDEN = /^(expo-sqlite|src\/(drafts|dbTransaction|interviewerDb))$/;
const EXTS = [".web.tsx", ".web.ts", ".tsx", ".ts", "/index.web.tsx", "/index.web.ts", "/index.tsx", "/index.ts"];
// Also follows require(); Metro bundles lazy requires too. Skips `import type` (erased by Babel) and `typeof import(...)` type positions.
const IMPORT = /(?:import|export)\s(?!type[\s{])[^'"]*?from\s*["']([^"']+)["']|import\s*["']([^"']+)["']|(?<!typeof\s)(?:import|require)\(\s*["']([^"']+)["']\s*\)/g;

function resolveFile(from: string, spec: string): string | null {
  const base = resolve(from, "..", spec);
  if (existsSync(base) && statSync(base).isFile()) return base;
  for (const ext of EXTS) if (existsSync(base + ext)) return base + ext;
  return null;
}

function routes(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? routes(path) : /\.tsx?$/.test(name) ? [path] : [];
  });
}

test("no web route reaches expo-sqlite or the native stores", () => {
  const parent = new Map<string, string>();
  const queue = routes(join(root, "app"));
  queue.forEach((f) => parent.set(f, ""));
  const hits: string[] = [];
  while (queue.length) {
    const file = queue.shift() as string;
    const src = readFileSync(file, "utf8");
    for (const m of src.matchAll(IMPORT)) {
      const spec = m[1] ?? m[2] ?? m[3];
      if (!spec.startsWith(".")) {
        if (FORBIDDEN.test(spec)) hits.push(`${file.replace(root + "/", "")} -> ${spec}`);
        continue;
      }
      const target = resolveFile(file, spec);
      if (!target || parent.has(target)) continue;
      const rel = target.replace(root + "/", "").replace(/\.(web\.)?tsx?$/, "");
      if (FORBIDDEN.test(rel)) {
        hits.push(`${file.replace(root + "/", "")} -> ${rel}`);
        continue;
      }
      parent.set(target, file);
      queue.push(target);
    }
  }
  expect(parent.size).toBeGreaterThan(20);
  expect(hits).toEqual([]);
});
