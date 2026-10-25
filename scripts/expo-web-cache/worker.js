/* Generated release metadata is injected by build-expo-web-cache.mjs. */
const manifest = __DIGITVA_ASSET_MANIFEST__;
const cachePrefix = "digitva-web:";
const cacheName = `${cachePrefix}${manifest.release}:${manifest.manifest_sha256}`;
// An old worker may still control a new page: shared unversioned paths must always use the network.
const assets = new Map(manifest.assets.filter((asset) => asset.cacheable === true).map((asset) => [asset.path, asset]));

/** Store only a verified public build asset; cookies and API responses never enter this cache. */
async function downloadAsset(path) {
  const response = await fetch(path, { credentials: "omit", cache: "no-cache", redirect: "error" });
  if (!response.ok || response.type === "opaque") throw new Error("asset_unavailable");
  const bytes = await response.clone().arrayBuffer();
  const expected = assets.get(path);
  if (bytes.byteLength !== expected.size) throw new Error("asset_size_mismatch");
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const hex = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== expected.sha256) throw new Error("asset_hash_mismatch");
  await (await caches.open(cacheName)).put(path, response.clone());
  return response;
}

// Default activation waits for old tabs to close. Never replace a running interview's build.
self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key.startsWith(cachePrefix) && key !== cacheName).map((key) => caches.delete(key)),
  )));
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || event.request.mode === "navigate" ||
      url.origin !== self.location.origin || url.search || !assets.has(url.pathname)) return;
  event.respondWith((async () => {
    const cached = await (await caches.open(cacheName)).match(url.pathname);
    return cached || downloadAsset(url.pathname);
  })());
});

let warming;
self.addEventListener("message", (event) => {
  if (event.data?.type !== "warm-public-assets" || event.data.release !== manifest.release) return;
  // Sequential requests keep background downloads from competing with foreground form requests.
  if (!warming) warming = (async () => {
    const cache = await caches.open(cacheName);
    for (const path of assets.keys()) {
      if (await cache.match(path)) continue;
      try { await downloadAsset(path); } catch { break; }
    }
  })().finally(() => { warming = undefined; });
  event.waitUntil(warming);
});
