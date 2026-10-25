import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash, webcrypto } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
import vm from "node:vm";

import { buildAssetCache } from "../build-expo-web-cache.mjs";

test("single-output HTML paints the saved theme before hydration, including blocked storage", () => {
  const html = readFileSync(new URL("../../mobile/digitva-collect/public/index.html", import.meta.url), "utf8");
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  assert.match(html, /html, body, #root[^}]*background: var\(--digitva-page-background\)/);
  assert.match(html, /id="digitva-startup" role="status"/);
  for (const [preference, systemDark, expectedDark] of [
    ["light", true, false], ["dark", false, true], [null, true, true], ["system", false, false],
    ["invalid", true, true], ["blocked", true, true],
  ]) {
    const properties = {};
    const style = { setProperty: (name, value) => { properties[name] = value; } };
    vm.runInNewContext(script, {
      localStorage: { getItem: (key) => {
        assert.equal(key, "ui_theme");
        if (preference === "blocked") throw new Error("Storage denied");
        return preference;
      } },
      window: { matchMedia: () => ({ matches: systemDark }) },
      document: { documentElement: { style } },
    });
    assert.equal(properties["--digitva-page-background"], expectedDark ? "#131E2E" : "#F6F8FB");
    assert.equal(style.colorScheme, expectedDark ? "dark" : "light");
  }
});

function fixture(t) {
  const dist = mkdtempSync(join(tmpdir(), "digitva-assets-"));
  t.after(() => rmSync(dist, { recursive: true, force: true }));
  mkdirSync(join(dist, "_expo/static/js/web"), { recursive: true });
  writeFileSync(join(dist, "index.html"), "<html><head></head></html>");
  const path = "_expo/static/js/web/entry-" + "a".repeat(32) + ".js";
  writeFileSync(join(dist, path), "public bundle");
  return { dist, path };
}

function whoMetadata(release, sourceCommit, overrides = {}) {
  const files = [{ path: "index.js", size: 3, sha256: createHash("sha256").update("abc").digest("hex") }];
  return {
    schema: 1,
    release,
    package_name: "@drguptavivek/who-2022-va",
    package_version: "1.2.3",
    source_commit: sourceCommit,
    artifact_name: `${release}-who-package.tgz`,
    artifact_sha256: "b".repeat(64),
    package_json_sha256: "c".repeat(64),
    dist_sha256: createHash("sha256").update(JSON.stringify(files)).digest("hex"),
    files,
    ...overrides,
  };
}

test("publishes a compact WHO component projection when a matched build header is supplied", (t) => {
  const { dist } = fixture(t);
  const release = "expo-web-v1";
  const sourceCommit = "a".repeat(40);
  const manifest = buildAssetCache(dist, release, sourceCommit, whoMetadata(release, sourceCommit));
  assert.deepEqual(manifest.components.who, {
    package_name: "@drguptavivek/who-2022-va",
    package_version: "1.2.3",
    source_commit: sourceCommit,
    artifact_sha256: "b".repeat(64),
    dist_sha256: whoMetadata(release, sourceCommit).dist_sha256,
  });
  assert.equal(Object.hasOwn(manifest.components.who, "files"), false);
});

test("CLI accepts the optional WHO metadata JSON path", (t) => {
  const { dist } = fixture(t);
  const release = "release-cli";
  const sourceCommit = "a".repeat(40);
  const metadataPath = join(dist, "who-build.json");
  writeFileSync(metadataPath, JSON.stringify(whoMetadata(release, sourceCommit)));
  execFileSync(process.execPath, [
    fileURLToPath(new URL("../build-expo-web-cache.mjs", import.meta.url)),
    dist, release, sourceCommit, metadataPath,
  ], { stdio: "pipe" });
  const manifest = JSON.parse(readFileSync(join(dist, "asset-manifest.json"), "utf8"));
  assert.equal(manifest.components.who.package_name, "@drguptavivek/who-2022-va");
});

test("rejects a WHO header with invalid identity, semver or digest fields", (t) => {
  const { dist } = fixture(t);
  const release = "release-1";
  const sourceCommit = "a".repeat(40);
  for (const [field, value, pattern] of [
    ["package_name", "wrong", /package_name/],
    ["package_version", "1", /package_version/],
    ["artifact_sha256", "bad", /artifact_sha256/],
    ["package_json_sha256", "bad", /package_json_sha256/],
    ["dist_sha256", "bad", /dist_sha256/],
    ["source_commit", "b".repeat(40), /source commit/],
    ["release", "other", /release mismatch/],
  ]) {
    const metadata = whoMetadata(release, sourceCommit, { [field]: value });
    assert.throws(() => buildAssetCache(dist, release, sourceCommit, metadata), pattern, field);
  }
});

test("deterministic manifest includes only public build assets and generates valid scripts", (t) => {
  const { dist, path } = fixture(t);
  mkdirSync(join(dist, "private"));
  writeFileSync(join(dist, "private/clinical.json"), "not public");
  const manifest = buildAssetCache(dist, "release-1", "a".repeat(40));
  assert.deepEqual(manifest.assets.map((asset) => asset.path), [`/app/${path}`]);
  assert.equal(manifest.assets[0].size, 13);
  assert.equal(manifest.assets[0].cacheable, true);
  assert.equal(manifest.assets[0].sha256, createHash("sha256").update("public bundle").digest("hex"));
  assert.deepEqual(buildAssetCache(dist, "release-1", "a".repeat(40)), manifest);
  assert.equal(readFileSync(join(dist, "index.html"), "utf8").match(/cache-register.js/g).length, 1);
  new vm.Script(readFileSync(join(dist, "asset-worker.js"), "utf8"));
  new vm.Script(readFileSync(join(dist, "cache-register.js"), "utf8"));
  assert.notEqual(buildAssetCache(dist, "release-2", "b".repeat(40)).manifest_sha256, manifest.manifest_sha256);
});

test("manifest groups only the deferred WHO runtime and its hashed JS closure", (t) => {
  const { dist } = fixture(t);
  const runtime = "_expo/static/js/web/whoRuntimeModule-" + "c".repeat(32) + ".js";
  const nested = "_expo/static/js/web/whoNested-" + "d".repeat(32) + ".js";
  const coding = "_expo/static/js/web/CodingScreen-" + "e".repeat(32) + ".js";
  writeFileSync(join(dist, runtime), `import "${nested.split("/").at(-1)}";`);
  writeFileSync(join(dist, nested), "nested WHO runtime");
  writeFileSync(join(dist, coding), "coding runtime");
  const manifest = buildAssetCache(dist, "release", "a".repeat(40));
  assert.deepEqual(manifest.groups.interviewRuntime, [
    `/app/${nested}`,
    `/app/${runtime}`,
  ]);
  assert.equal(manifest.groups.interviewRuntime.includes(`/app/${coding}`), false);
});

test("an old worker cannot serve an unversioned asset reused by the next release", (t) => {
  const { dist } = fixture(t);
  mkdirSync(join(dist, "assets"));
  const sharedPath = "/app/assets/logo.png";
  const scripts = [];
  for (const [release, body] of [["release-1", "old logo"], ["release-2", "new logo"]]) {
    writeFileSync(join(dist, "assets/logo.png"), body);
    const manifest = buildAssetCache(dist, release, "a".repeat(40));
    const asset = manifest.assets.find((item) => item.path === sharedPath);
    assert.equal(asset.cacheable, false);
    assert.equal(asset.sha256, createHash("sha256").update(body).digest("hex"));
    scripts.push(readFileSync(join(dist, "asset-worker.js"), "utf8"));
  }
  for (const script of scripts) {
    const handlers = {};
    vm.runInNewContext(script, {
      self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
      caches: { open: () => assert.fail("An unversioned asset must not read an old cache") }, URL,
    });
    handlers.fetch({
      request: { url: `https://example.com${sharedPath}`, method: "GET" },
      respondWith: () => assert.fail("The new release's unversioned asset must reach the network"),
    });
  }
});

test("refuses missing runtime, unsafe identities, symlinks and hidden files", (t) => {
  const { dist } = fixture(t);
  assert.throws(() => buildAssetCache(dist, "<script>", "a".repeat(40)), /identity/);
  assert.throws(() => buildAssetCache(dist, "release", "bad"), /identity/);
  symlinkSync(join(dist, "index.html"), join(dist, "_expo/leak.js"));
  assert.throws(() => buildAssetCache(dist, "release", "a".repeat(40)), /Symlink/);
  rmSync(join(dist, "_expo/leak.js"));
  writeFileSync(join(dist, "_expo/.env"), "secret");
  assert.throws(() => buildAssetCache(dist, "release", "a".repeat(40)), /Unsafe/);
});

test("worker caches verified assets, ignores clinical/navigation requests, and retries failed downloads", async (t) => {
  const { dist, path } = fixture(t);
  buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  const entries = new Map();
  const cache = { match: async (key) => entries.get(key)?.clone(), put: async (key, value) => entries.set(key, value) };
  const calls = [];
  let body = "public bundle";
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: { open: async () => cache }, URL, crypto: webcrypto,
    fetch: async (url, options) => { calls.push([url, options]); return new Response(body); },
  });
  for (const request of [
    { url: "https://example.com/api/v1/private", method: "GET" },
    { url: "https://example.com/app/workspace", method: "GET", mode: "navigate" },
    { url: `https://other.com/app/${path}`, method: "GET" },
    { url: `https://example.com/app/${path}?token=secret`, method: "GET" },
    { url: `https://example.com/app/${path}`, method: "POST" },
  ]) handlers.fetch({ request, respondWith: () => assert.fail("Must not intercept private request") });
  assert.equal(calls.length, 0);
  function get() {
    let response;
    handlers.fetch({ request: { url: `https://example.com/app/${path}`, method: "GET" }, respondWith: (promise) => { response = promise; } });
    return response;
  }
  body = "bad";
  await assert.rejects(get(), /size_mismatch/);
  assert.equal(entries.size, 0);
  body = "PUBLIC BUNDLE";
  await assert.rejects(get(), /hash_mismatch/);
  assert.equal(entries.size, 0);
  body = "public bundle";
  assert.equal(await (await get()).text(), body);
  assert.equal(entries.size, 1);
  assert.equal(calls.at(-1)[1].credentials, "omit");
  await get();
  assert.equal(calls.length, 3);
});

test("worker warms only the WHO group, retains completed assets and retries a bad asset", async (t) => {
  const { dist } = fixture(t);
  const runtime = "_expo/static/js/web/whoRuntimeModule-" + "c".repeat(32) + ".js";
  const dependency = "_expo/static/js/web/aWhoDependency-" + "d".repeat(32) + ".js";
  writeFileSync(join(dist, runtime), `import "${dependency.split("/").at(-1)}";`);
  writeFileSync(join(dist, dependency), "WHO dependency");
  const manifest = buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  const entries = new Map();
  const cache = {
    match: async (key) => entries.get(key)?.clone(),
    put: async (key, value) => entries.set(key, value),
  };
  const calls = [];
  const bodies = new Map([
    [`/app/${dependency}`, "WHO dependency"],
    [`/app/${runtime}`, "import \"aWhoDependency-" + "d".repeat(32) + ".js\";"],
  ]);
  let corruptRuntime = true;
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: { open: async () => cache }, URL, crypto: webcrypto, AbortController,
    fetch: async (url, options) => {
      calls.push([url, options]);
      const path = new URL(url, "https://example.com").pathname;
      return new Response(path === `/app/${runtime}` && corruptRuntime ? "corrupt" : bodies.get(path));
    },
  });
  let firstWarm;
  handlers.message({
    source: { id: "client-a" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 1 },
    waitUntil: (promise) => { firstWarm = promise; },
  });
  await firstWarm;
  assert.deepEqual([...entries.keys()], [`/app/${dependency}`]);
  assert.deepEqual(calls.map(([url]) => new URL(url, "https://example.com").pathname), [`/app/${dependency}`, `/app/${runtime}`]);

  corruptRuntime = false;
  let retry;
  handlers.message({
    source: { id: "client-a" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 2 },
    waitUntil: (promise) => { retry = promise; },
  });
  await retry;
  assert.deepEqual([...entries.keys()], [`/app/${dependency}`, `/app/${runtime}`]);
  assert.equal(calls.filter(([url]) => new URL(url, "https://example.com").pathname === `/app/${dependency}`).length, 1);
});

test("worker cancellation aborts a pending WHO warm and stale starts do not restart it", async (t) => {
  const { dist } = fixture(t);
  const runtime = "_expo/static/js/web/whoRuntimeModule-" + "c".repeat(32) + ".js";
  writeFileSync(join(dist, runtime), "WHO runtime");
  buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  let resolveFetch;
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: { open: async () => ({ match: async () => undefined, put: async () => undefined }) }, URL, crypto: webcrypto, AbortController,
    fetch: (url, options) => new Promise((resolve, reject) => {
      resolveFetch = () => resolve(new Response("WHO runtime"));
      options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
    }),
  });
  let warming;
  handlers.message({
    source: { id: "client-a" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 4 },
    waitUntil: (promise) => { warming = promise; },
  });
  await new Promise((resolve) => setTimeout(resolve, 0));
  handlers.message({
    source: { id: "client-a" },
    data: { type: "cancel-interview-assets", release: "release", generation: 5 },
    waitUntil: () => assert.fail("cancel does not wait for a download"),
  });
  await warming;
  assert.equal(resolveFetch !== undefined, true);
  resolveFetch();
  let stale;
  handlers.message({
    source: { id: "client-a" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 4 },
    waitUntil: (promise) => { stale = promise; },
  });
  assert.equal(stale, undefined);
});

test("a new browser client may restart with a fresh generation after an old client reached 40", async (t) => {
  const { dist } = fixture(t);
  const runtime = "_expo/static/js/web/whoRuntimeModule-" + "c".repeat(32) + ".js";
  writeFileSync(join(dist, runtime), "WHO runtime");
  buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  const entries = new Map();
  const cache = { match: async (key) => entries.get(key)?.clone(), put: async (key, value) => entries.set(key, value) };
  let calls = 0;
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: { open: async () => cache }, URL, crypto: webcrypto, AbortController,
    fetch: async () => { calls += 1; return new Response("WHO runtime"); },
  });
  let oldWarm;
  handlers.message({
    source: { id: "old-client" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 40 },
    waitUntil: (promise) => { oldWarm = promise; },
  });
  await oldWarm;
  entries.clear();
  let freshWarm;
  handlers.message({
    source: { id: "new-client" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 2 },
    waitUntil: (promise) => { freshWarm = promise; },
  });
  await freshWarm;
  assert.equal(calls, 2);
  let sourceMissing;
  handlers.message({
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 3 },
    waitUntil: (promise) => { sourceMissing = promise; },
  });
  assert.equal(sourceMissing, undefined);
});

test("an old client's cancellation cannot abort a newer client's warm job", async (t) => {
  const { dist } = fixture(t);
  const runtime = "_expo/static/js/web/whoRuntimeModule-" + "c".repeat(32) + ".js";
  writeFileSync(join(dist, runtime), "WHO runtime");
  buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  const entries = new Map();
  const cache = { match: async () => undefined, put: async (key, value) => entries.set(key, value) };
  let fetchCount = 0;
  let oldStarted;
  let newStarted;
  const oldFetchStarted = new Promise((resolve) => { oldStarted = resolve; });
  const newFetchStarted = new Promise((resolve) => { newStarted = resolve; });
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { location: { origin: "https://example.com" }, addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: { open: async () => cache }, URL, crypto: webcrypto, AbortController,
    fetch: async (_url, options) => new Promise((resolve, reject) => {
      fetchCount += 1;
      if (fetchCount === 1) oldStarted();
      else newStarted();
      options.signal.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
      if (fetchCount > 1) resolve(new Response("WHO runtime"));
    }),
  });
  let oldWarm;
  handlers.message({
    source: { id: "old-client" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 40 },
    waitUntil: (promise) => { oldWarm = promise; },
  });
  await oldFetchStarted;
  let newWarm;
  handlers.message({
    source: { id: "new-client" },
    data: { type: "warm-interview-assets", group: "interviewRuntime", release: "release", generation: 2 },
    waitUntil: (promise) => { newWarm = promise; },
  });
  await newFetchStarted;
  handlers.message({
    source: { id: "old-client" },
    data: { type: "cancel-interview-assets", release: "release", generation: 41 },
    waitUntil: () => assert.fail("cancel does not wait for a download"),
  });
  await Promise.all([oldWarm, newWarm]);
  assert.equal(entries.size, 1);
});

test("registration waits for page load but never warms anonymously", async (t) => {
  const { dist } = fixture(t);
  buildAssetCache(dist, "release", "a".repeat(40));
  for (const connection of [undefined, {}, { effectiveType: "unknown" },
    { effectiveType: "4g", saveData: true }, { effectiveType: "3g" },
    { effectiveType: "slow-2g" }, { effectiveType: "4g" }]) {
    let onLoad;
    let idle;
    const registrations = [];
    const messages = [];
    vm.runInNewContext(readFileSync(join(dist, "cache-register.js"), "utf8"), {
      document: { readyState: "loading", visibilityState: "visible" },
      navigator: { connection, onLine: true, serviceWorker: {
        register: async (...args) => { registrations.push(args); },
        ready: Promise.resolve({ active: { postMessage: (message) => messages.push(message) } }),
      } },
      window: { isSecureContext: true, addEventListener: (_, callback) => { onLoad = callback; },
        requestIdleCallback: (callback) => { idle = callback; } },
    });
    assert.equal(registrations.length, 0);
    await onLoad();
    assert.equal(registrations[0][0], "/app/asset-worker.js");
    assert.equal(registrations[0][1].updateViaCache, "none");
    assert.equal(idle, undefined);
    assert.deepEqual(messages, []);
  }
});

test("activation removes only previous DigitVA public caches without forcing control", async (t) => {
  const { dist } = fixture(t);
  const manifest = buildAssetCache(dist, "release", "a".repeat(40));
  const handlers = {};
  const deleted = [];
  vm.runInNewContext(readFileSync(join(dist, "asset-worker.js"), "utf8"), {
    self: { addEventListener: (type, handler) => { handlers[type] = handler; } },
    caches: {
      keys: async () => ["other-app-cache", "digitva-web:old:hash", `digitva-web:release:${manifest.manifest_sha256}`],
      delete: async (key) => { deleted.push(key); },
    },
  });
  let activation;
  handlers.activate({ waitUntil: (promise) => { activation = promise; } });
  await activation;
  assert.deepEqual(deleted, ["digitva-web:old:hash"]);
});
