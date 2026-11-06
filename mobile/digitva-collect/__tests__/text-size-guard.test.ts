/**
 * Settings > Display > Text size reaches every phone screen only through `useTheme().typography` / `.fontSize`.
 * This scan fails with file:line when a phone screen or shared component imports the static (Medium) text tokens.
 */
import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

const ROOT = join(__dirname, "..");
const SCAN = ["src/nativeRoutes", "src/ui", "src/nativeShell", "src/coding", "src/standalone", "src/home"];
/** Fixed-height bars keep the static sizes: the 48pt header and 56pt tab bar (NativeChrome), the header DEMO badge. */
const ALLOW = new Set(["src/nativeShell/NativeChrome.tsx", "src/DemoBadge.tsx"]);
const STATIC_IMPORT = /import \{[^}]*\b(typography|fontSize)\b[^}]*\} from "(\.\.\/)*(\.\/)?theme"/;

function files(path: string): string[] {
  const full = join(ROOT, path);
  if (!statSync(full, { throwIfNoEntry: false })) return [];
  if (!statSync(full).isDirectory()) return [path];
  return readdirSync(full).flatMap((name) => files(join(path, name)));
}

const topLevel = readdirSync(join(ROOT, "src")).filter((name) => name.endsWith(".tsx")).map((name) => `src/${name}`);

it("phone screens and shared components read text sizes from the theme", () => {
  const scanned = [...SCAN.flatMap(files), ...topLevel].filter((file) => /\.tsx?$/.test(file) && !ALLOW.has(file));
  expect(scanned).toContain("src/ui.tsx");
  const found = scanned.flatMap((file) =>
    readFileSync(join(ROOT, file), "utf8").split("\n").flatMap((line, index) => (STATIC_IMPORT.test(line) ? [`${file}:${index + 1}`] : [])));
  expect(found).toEqual([]);
});
