/** Update check (digitva-2vrs): server first, GitHub fallback, once a day, silent when nothing is reachable. */
const mockPrefs: Record<string, string> = {};
jest.mock("../src/preferences", () => ({
  getUiPreference: async (key: string) => mockPrefs[key] ?? null,
  setUiPreference: async (key: string, value: string) => { mockPrefs[key] = value; },
}));
jest.mock("../src/appVersion", () => ({ APP_VERSION: "0.3.2" }));

import { checkForUpdate, checkForUpdateDaily, GITHUB_RELEASES_URL, versionCode } from "../src/updateCheck";

const SERVER = "https://va.example.org/";
const SERVER_URL = "https://va.example.org/api/v1/app/android/latest";
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body });
const fail = { ok: false, status: 404, json: async () => ({}) };
const serverReply = (version: string) => ok({ version, version_code: versionCode(version), url: "https://va.example.org/download/android" });
const release = (tag: string, extra: Record<string, unknown> = {}) => ({
  tag_name: tag, ...extra,
  assets: [
    { name: "digitva-collect-1-armeabi-v7a.apk", browser_download_url: `https://gh/${tag}/v7a.apk` },
    { name: "digitva-collect-1-arm64-v8a.apk", browser_download_url: `https://gh/${tag}/arm64.apk` },
  ],
});
let routes: Record<string, unknown>;
const fetchMock = jest.fn(async (url: string) => {
  const reply = routes[url];
  if (reply instanceof Error) throw reply;
  return reply ?? fail;
});

beforeEach(() => {
  for (const key of Object.keys(mockPrefs)) delete mockPrefs[key];
  routes = {};
  fetchMock.mockClear();
  (globalThis as { fetch: unknown }).fetch = fetchMock;
});

test("version code is the server's base code", () => {
  expect([versionCode("0.3.2"), versionCode("1.12.30"), versionCode("0.3"), versionCode("x")]).toEqual([302, 11230, null, null]);
});

test("a newer server release is reported with the server's download url", async () => {
  routes[SERVER_URL] = serverReply("0.3.10");
  expect(await checkForUpdate(SERVER)).toEqual({ status: "available", version: "0.3.10", url: "https://va.example.org/download/android" });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("the same or an older release is not an update", async () => {
  routes[SERVER_URL] = serverReply("0.3.2");
  expect(await checkForUpdate(SERVER)).toEqual({ status: "current" });
  routes[SERVER_URL] = serverReply("0.2.9");
  expect(await checkForUpdate(SERVER)).toEqual({ status: "current" });
});

test("an unreachable server falls back to the newest android-v* GitHub release (arm64, no drafts)", async () => {
  routes[SERVER_URL] = new Error("network");
  routes[GITHUB_RELEASES_URL] = ok([
    release("v9.9.9"),
    release("android-v0.4.0", { draft: true }),
    release("android-v0.3.5"),
    release("android-v0.3.9"),
    release("android-v0.3.7"),
  ]);
  expect(await checkForUpdate(SERVER)).toEqual({ status: "available", version: "0.3.9", url: "https://gh/android-v0.3.9/arm64.apk" });
});

test("a server with no release (404) also falls back to GitHub", async () => {
  routes[GITHUB_RELEASES_URL] = ok([release("android-v0.3.2")]);
  expect(await checkForUpdate(SERVER)).toEqual({ status: "current" });
  expect(fetchMock).toHaveBeenCalledTimes(2);
});

test("both unreachable is unknown, not an error", async () => {
  routes[SERVER_URL] = new Error("offline");
  routes[GITHUB_RELEASES_URL] = new Error("offline");
  await expect(checkForUpdate(SERVER)).resolves.toEqual({ status: "unknown" });
  routes[GITHUB_RELEASES_URL] = { ok: false, status: 403, json: async () => ({}) };
  await expect(checkForUpdate(SERVER)).resolves.toEqual({ status: "unknown" });
});

test("the start-up check runs once a day and is retried after an unreachable try", async () => {
  const t0 = 1_800_000_000_000;
  routes[SERVER_URL] = new Error("offline");
  routes[GITHUB_RELEASES_URL] = new Error("offline");
  expect(await checkForUpdateDaily(SERVER, t0)).toEqual({ status: "unknown" });
  expect(mockPrefs.update_check_at).toBeUndefined();

  routes[SERVER_URL] = serverReply("0.3.4");
  expect((await checkForUpdateDaily(SERVER, t0 + 1000))?.status).toBe("available");
  fetchMock.mockClear();
  expect(await checkForUpdateDaily(SERVER, t0 + 3_600_000)).toBeUndefined();
  expect(fetchMock).not.toHaveBeenCalled();
  expect((await checkForUpdateDaily(SERVER, t0 + 1000 + 24 * 3_600_000))?.status).toBe("available");
});

test("a non-https download link is never offered", async () => {
  routes[SERVER_URL] = ok({ version: "0.4.0", version_code: 400, url: "intent://evil#Intent;end" });
  expect(await checkForUpdate(SERVER)).toEqual({ status: "unknown" });
});
