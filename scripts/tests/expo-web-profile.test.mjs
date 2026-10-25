import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  CANONICAL_WHO_INSTRUMENT_MARKER,
  INITIAL_GZIP_LIMIT,
  INITIAL_RAW_LIMIT,
  parseInitialScripts,
  profileExpoWeb,
} from "../profile-expo-web.mjs";

const hash = (body) => createHash("sha256").update(body).digest("hex");
const hex = (character) => character.repeat(32);

function fixture(t, { initial = "safe", runtime = true, marker = true, release = "expo-web-test", whoComponent = false, group = true } = {}) {
  const dist = mkdtempSync(join(tmpdir(), "digitva-web-profile-"));
  t.after(() => rmSync(dist, { recursive: true, force: true }));
  mkdirSync(join(dist, "_expo/static/js/web"), { recursive: true });
  const entry = "_expo/static/js/web/entry-" + hex("a") + ".js";
  const common = "_expo/static/js/web/__common-" + hex("b") + ".js";
  const deferred = "_expo/static/js/web/feature-" + hex("c") + ".js";
  const who = "_expo/static/js/web/whoRuntimeModule-" + hex("d") + ".js";
  const register = "cache-register.js";
  for (const [path, body] of [[entry, "entry"], [common, "common"], [deferred, "feature"], [register, "register"]]) {
    writeFileSync(join(dist, path), body);
  }
  if (runtime) writeFileSync(join(dist, who), marker ? `who runtime ${CANONICAL_WHO_INSTRUMENT_MARKER}` : "who runtime");
  const scripts = initial === "safe"
    ? `<script src="/app/${entry}"></script><script src='/app/${common}'></script><script src="/app/${register}" defer></script>`
    : initial;
  writeFileSync(join(dist, "index.html"), `<html><head><link rel="modulepreload" href="/app/${common}">${scripts}</head></html>`);
  const assets = [entry, common, deferred, ...(runtime ? [who] : []), register].map((path) => {
    const body = readFileSync(join(dist, path));
    return { path: `/app/${path}`, size: body.byteLength, sha256: hash(body), cacheable: true };
  });
  const manifest = {
    schema: 1, release, source_commit: "a".repeat(40), assets,
  };
  if (group) manifest.groups = { interviewRuntime: runtime ? [`/app/${who}`] : [] };
  if (whoComponent) manifest.components = { who: {
    package_name: "@drguptavivek/who-2022-va",
    package_version: "1.2.3",
    source_commit: "a".repeat(40),
    artifact_sha256: "b".repeat(64),
    dist_sha256: "c".repeat(64),
  } };
  writeFileSync(join(dist, "asset-manifest.json"), JSON.stringify(manifest));
  return { dist, entry, common, deferred, who, register };
}

test("extracts every initial script in HTML order", () => {
  assert.deepEqual(parseInitialScripts(`before<link rel="modulepreload" href="/app/common.js"><script src='/app/entry.js'></script><script src="/app/cache-register.js"></script>`), [
    { kind: "script", url: "/app/entry.js" },
    { kind: "script", url: "/app/cache-register.js" },
  ]);
});

test("profiles the complete initial set, deferred runtime, hashes, and deterministic gzip", (t) => {
  const fixturePaths = fixture(t);
  const output = join(fixturePaths.dist, "profile.json");
  const report = profileExpoWeb({ dist: fixturePaths.dist, outputPath: output });
  assert.deepEqual(report.initial.scripts.map((item) => item.path), [
    `/app/${fixturePaths.entry}`,
    `/app/${fixturePaths.common}`,
    `/app/${fixturePaths.register}`,
  ]);
  assert.equal(report.deferred.runtime_chunks.length, 1);
  assert.equal(report.deferred.runtime_chunks[0].path, `/app/${fixturePaths.who}`);
  assert.equal(report.deferred.runtime_chunks[0].sha256, hash(`who runtime ${CANONICAL_WHO_INSTRUMENT_MARKER}`));
  assert.deepEqual(report.canonical_instrument.initial_chunks, []);
  assert.deepEqual(report.canonical_instrument.deferred_chunks, [`/app/${fixturePaths.who}`]);
  assert.equal(report.gates.passed, true);
  assert.equal(report.total_javascript.raw_bytes, report.initial.raw_bytes + report.deferred.raw_bytes);
  assert.equal(report.largest_chunks[0].raw_bytes >= report.largest_chunks.at(-1).raw_bytes, true);
  assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), report);
  assert.equal(report.initial.raw_bytes < INITIAL_RAW_LIMIT, true);
  assert.equal(report.initial.gzip_bytes < INITIAL_GZIP_LIMIT, true);
});

test("reports matched WHO metadata and validates its deferred cache group", (t) => {
  const fixturePaths = fixture(t, { release: "expo-web-v1", whoComponent: true });
  const report = profileExpoWeb({ dist: fixturePaths.dist, requireWhoComponent: true });
  assert.deepEqual(report.who_component, {
    package_name: "@drguptavivek/who-2022-va",
    package_version: "1.2.3",
    source_commit: "a".repeat(40),
    artifact_sha256: "b".repeat(64),
    dist_sha256: "c".repeat(64),
  });
});

test("CLI enables strict WHO validation with --require-who", (t) => {
  const fixturePaths = fixture(t, { whoComponent: true });
  const output = join(fixturePaths.dist, "profile.json");
  execFileSync(process.execPath, [
    fileURLToPath(new URL("../profile-expo-web.mjs", import.meta.url)),
    fixturePaths.dist, output, "--require-who",
  ], { stdio: "pipe" });
  assert.deepEqual(JSON.parse(readFileSync(output, "utf8")).who_component, {
    package_name: "@drguptavivek/who-2022-va",
    package_version: "1.2.3",
    source_commit: "a".repeat(40),
    artifact_sha256: "b".repeat(64),
    dist_sha256: "c".repeat(64),
  });
});

test("requires WHO metadata for production releases even without the CLI flag", (t) => {
  const fixturePaths = fixture(t, { release: "expo-web-v1", group: false });
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist }), /WHO component metadata is missing/);
});

test("rejects invalid WHO component metadata", (t) => {
  for (const [field, value, pattern] of [
    ["package_name", "wrong", /package_name/],
    ["package_version", "1", /package_version/],
    ["artifact_sha256", "bad", /artifact_sha256/],
    ["dist_sha256", "bad", /dist_sha256/],
    ["source_commit", "b".repeat(40), /source_commit/],
  ]) {
    const fixturePaths = fixture(t, { whoComponent: true });
    const manifestPath = join(fixturePaths.dist, "asset-manifest.json");
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    manifest.components.who[field] = value;
    writeFileSync(manifestPath, JSON.stringify(manifest));
    assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist, requireWhoComponent: true }), pattern, field);
  }
});

test("requires a non-empty untampered WHO interviewRuntime group containing the deferred instrument", (t) => {
  const empty = fixture(t, { whoComponent: true, group: true });
  const emptyManifest = JSON.parse(readFileSync(join(empty.dist, "asset-manifest.json"), "utf8"));
  emptyManifest.groups.interviewRuntime = [];
  writeFileSync(join(empty.dist, "asset-manifest.json"), JSON.stringify(emptyManifest));
  assert.throws(() => profileExpoWeb({ dist: empty.dist, requireWhoComponent: true }), /group is empty/);

  const tampered = fixture(t, { whoComponent: true, group: true });
  const tamperedManifest = JSON.parse(readFileSync(join(tampered.dist, "asset-manifest.json"), "utf8"));
  tamperedManifest.groups.interviewRuntime = [`/app/${tampered.deferred}`];
  writeFileSync(join(tampered.dist, "asset-manifest.json"), JSON.stringify(tamperedManifest));
  assert.throws(() => profileExpoWeb({ dist: tampered.dist, requireWhoComponent: true }), /canonical deferred instrument/);
});

test("rejects a tampered ordinary manifest asset hash", (t) => {
  const fixturePaths = fixture(t);
  const manifestPath = join(fixturePaths.dist, "asset-manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  manifest.assets[0].sha256 = "0".repeat(64);
  writeFileSync(manifestPath, JSON.stringify(manifest));
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist }), /Manifest hash or size mismatch/);
});

test("rejects external URLs and path traversal without touching JavaScript", (t) => {
  const fixturePaths = fixture(t, { initial: `<script src="https://evil.example/steal.js"></script>` });
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist }), /External or unsupported/);
  const traversal = fixture(t, { initial: `<script src="/app/../secret.js"></script>` });
  assert.throws(() => profileExpoWeb({ dist: traversal.dist }), /Unsafe (initial )?script path/);
});

test("rejects an eagerly emitted canonical WHO instrument marker", (t) => {
  const fixturePaths = fixture(t);
  const entryBody = `entry ${CANONICAL_WHO_INSTRUMENT_MARKER}`;
  writeFileSync(join(fixturePaths.dist, fixturePaths.entry), entryBody);
  const manifestPath = join(fixturePaths.dist, "asset-manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entry = manifest.assets.find((asset) => asset.path === `/app/${fixturePaths.entry}`);
  entry.size = Buffer.byteLength(entryBody);
  entry.sha256 = hash(entryBody);
  writeFileSync(manifestPath, JSON.stringify(manifest));
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist }), /must remain deferred/);
});

test("detects when the canonical WHO instrument marker is absent", (t) => {
  const fixturePaths = fixture(t, { marker: false });
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist }), /marker was not found/);
});

test("fails clearly when the runtime chunk is missing or eager", (t) => {
  const missing = fixture(t, { runtime: false });
  assert.throws(() => profileExpoWeb({ dist: missing.dist }), /expected deferred whoRuntimeModule/);
  const eager = fixture(t);
  const html = readFileSync(join(eager.dist, "index.html"), "utf8");
  writeFileSync(join(eager.dist, "index.html"), html.replace("</head>", `<script src="/app/${eager.who}"></script></head>`));
  assert.throws(() => profileExpoWeb({ dist: eager.dist }), /must not be an initial HTML script/);
});

test("writes a failed report with byte totals when initial gates are exceeded", (t) => {
  const fixturePaths = fixture(t);
  const oversized = "x".repeat(INITIAL_RAW_LIMIT + 1);
  writeFileSync(join(fixturePaths.dist, fixturePaths.entry), oversized);
  const manifestPath = join(fixturePaths.dist, "asset-manifest.json");
  const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
  const entry = manifest.assets.find((asset) => asset.path === `/app/${fixturePaths.entry}`);
  entry.size = Buffer.byteLength(oversized);
  entry.sha256 = hash(oversized);
  writeFileSync(manifestPath, JSON.stringify(manifest));
  const output = join(fixturePaths.dist, "profile.json");
  assert.throws(() => profileExpoWeb({ dist: fixturePaths.dist, outputPath: output }), /initial raw bytes/);
  const report = JSON.parse(readFileSync(output, "utf8"));
  assert.equal(report.gates.passed, false);
  assert.equal(report.gates.errors.some((error) => error.includes("initial raw bytes")), true);
});
