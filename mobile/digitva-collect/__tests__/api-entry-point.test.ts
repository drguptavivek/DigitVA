// src/api.ts re-exports the modules under src/api/ as plain consts so jest
// spies still work. Those modules import back from ../api, so the consts are
// only real when api.ts loads first: importing src/api/<x> directly from
// anywhere else would leave api.ts exporting undefined (digitva-r8nh.20).
import { readdirSync, readFileSync, statSync } from "fs";
import { join, relative, sep } from "path";

const ROOT = join(__dirname, "..");
const SCANNED = ["src", "app"];
const DIRECT = /(?:from\s+|require\(\s*|import\(\s*)["'][^"']*\bapi\/(types|intake|station|mentor|url)["']/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return files(path);
    return /\.(ts|tsx|js|jsx)$/.test(name) ? [path] : [];
  });
}

function allowed(path: string): boolean {
  const rel = relative(ROOT, path).split(sep).join("/");
  return rel === "src/api.ts" || rel.startsWith("src/api/");
}

test("only src/api.ts imports the modules under src/api/", () => {
  const offenders = SCANNED.flatMap((dir) => files(join(ROOT, dir)))
    .filter((path) => !allowed(path))
    .filter((path) => DIRECT.test(readFileSync(path, "utf8")))
    .map((path) => relative(ROOT, path));
  expect(offenders).toEqual([]);
});

test("the guard recognises a direct import", () => {
  expect(DIRECT.test('import { getCases } from "../api/intake";')).toBe(true);
  expect(DIRECT.test('import { getCases } from "../src/api";')).toBe(false);
  expect(DIRECT.test('import { x } from "./area/api";')).toBe(false);
});
