/**
 * Update check (digitva-2vrs): asks the enrolled server for the hosted APK (GET /api/v1/app/android/latest, public),
 * falls back to the newest android-v* GitHub release when the server has none or cannot be reached, and compares the
 * base version code (major*10000 + minor*100 + patch) with the installed version. It only reports; the app never
 * installs anything. Failures are silent: "unknown" is shown as "Couldn't check" in Settings and nowhere else.
 */
import { APP_VERSION } from "./appVersion";
import { getUiPreference, setUiPreference } from "./preferences";

export type UpdateResult = { status: "available"; version: string; url: string } | { status: "current" } | { status: "unknown" };

export const GITHUB_RELEASES_URL = "https://api.github.com/repos/drguptavivek/DigitVA/releases?per_page=10";
export const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 8_000;

/** "0.3.2" -> 302, the server's base version_code; null when it is not major.minor.patch. */
export function versionCode(version: string): number | null {
  const match = /^(\d+)\.(\d+)\.(\d+)$/.exec(version);
  return match ? Number(match[1]) * 10_000 + Number(match[2]) * 100 + Number(match[3]) : null;
}

async function getJson(url: string): Promise<unknown> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, { headers: { Accept: "application/json" }, signal: controller.signal });
    if (!response.ok) throw new Error(String(response.status));
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

interface Release { version: string; url: string }

async function fromServer(server: string): Promise<Release> {
  const body = (await getJson(`${server.replace(/\/+$/, "")}/api/v1/app/android/latest`)) as { version?: unknown; version_code?: unknown; url?: unknown };
  if (typeof body.version !== "string" || typeof body.url !== "string" || typeof body.version_code !== "number") throw new Error("bad_reply");
  return { version: body.version, url: body.url };
}

/** Newest non-draft android-v<x.y.z> release; its arm64 APK is the download (the common phone). */
async function fromGitHub(): Promise<Release> {
  const releases = (await getJson(GITHUB_RELEASES_URL)) as Array<{ tag_name?: string; draft?: boolean; prerelease?: boolean; assets?: Array<{ name?: string; browser_download_url?: string }> }>;
  let best: (Release & { code: number }) | undefined;
  for (const release of releases) {
    const version = /^android-v(\d+\.\d+\.\d+)$/.exec(release.tag_name ?? "")?.[1];
    if (!version || release.draft || release.prerelease) continue;
    const code = versionCode(version)!;
    const asset = release.assets?.find((item) => /arm64.*\.apk$/.test(item.name ?? ""));
    if (asset?.browser_download_url && (!best || code > best.code)) best = { version, url: asset.browser_download_url, code };
  }
  if (!best) throw new Error("no_release");
  return best;
}

/** Whether a newer APK is released. `server` is the enrolled server's origin; undefined skips straight to GitHub. */
export async function checkForUpdate(server?: string): Promise<UpdateResult> {
  let latest: Release | undefined;
  if (server) latest = await fromServer(server).catch(() => undefined);
  if (!latest) latest = await fromGitHub().catch(() => undefined);
  if (!latest) return { status: "unknown" };
  const hosted = versionCode(latest.version);
  const installed = versionCode(APP_VERSION);
  if (hosted === null || installed === null) return { status: "unknown" };
  return hosted > installed ? { status: "available", version: latest.version, url: latest.url } : { status: "current" };
}

/** The start-up check: at most once a day after an answer; an unreachable check is tried again at the next start. */
export async function checkForUpdateDaily(server: string | undefined, now = Date.now()): Promise<UpdateResult | undefined> {
  const last = Number(await getUiPreference("update_check_at")) || 0;
  if (now - last < CHECK_INTERVAL_MS && now >= last) return undefined;
  const result = await checkForUpdate(server);
  if (result.status !== "unknown") await setUiPreference("update_check_at", String(now));
  return result;
}
