import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
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

test("registration waits for page load and skips warming on slow or metered connections", async (t) => {
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
    if (connection?.effectiveType === "4g" && !connection.saveData) {
      assert.equal(typeof idle, "function");
      idle();
      assert.equal(messages[0].type, "warm-public-assets");
    } else assert.equal(idle, undefined);
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
