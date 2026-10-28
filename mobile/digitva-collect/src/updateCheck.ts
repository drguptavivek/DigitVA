/**
 * Checks the selected package's hosted APK first and matching GitHub release second. It only reports; the app never
 * installs anything. Failures are silent: "unknown" is shown as "Couldn't check" in Settings and nowhere else.
 */
import { APP_VERSION } from "./appVersion";
import { assertOnline } from "./network";
import { getUiPreference, setUiPreference } from "./preferences";
import { isPlusVariant } from "./appVariant";

export type UpdateResult = { status: "available"; version: string; url: string } | { status: "current" } | { status: "unknown" };
export type CompatibilityResult = { status: "compatible" | "mismatch"; buildRevision: string | null } | { status: "unknown" };

export const GITHUB_RELEASES_URL = "https://api.github.com/repos/drguptavivek/DigitVA/releases?per_page=10";
export const CHECK_INTERVAL_MS = 24 * 60 * 60 * 1000;
const TIMEOUT_MS = 8_000;

/** Base server code; Plus release counters affect ordering only when equal versions are compared. */
export function versionCode(version: string): number | null {
  const match = /^(\d+)\.(\d+)\.(\d+)(?:-plus(?:\.\d+)?)?$/.exec(version);
  return match ? Number(match[1]) * 10_000 + Number(match[2]) * 100 + Number(match[3]) : null;
}

async function getJson(url: string): Promise<unknown> {
  assertOnline();
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

export async function checkServerCompatibility(server: string): Promise<CompatibilityResult> {
  try {
    const body = await getJson(`${server.replace(/\/+$/, "")}/api/v1/app/version`) as { api_compatibility?: unknown; build_revision?: unknown };
    if (!Number.isSafeInteger(body.api_compatibility) || (body.api_compatibility as number) < 1 ||
      !(body.build_revision === null || (typeof body.build_revision === "string" && /^[a-f0-9]{40}$/.test(body.build_revision)))) return { status: "unknown" };
    return { status: body.api_compatibility === 1 ? "compatible" : "mismatch", buildRevision: body.build_revision as string | null };
  } catch {
    return { status: "unknown" };
  }
}

async function fromServer(server: string): Promise<Release> {
  const variant = isPlusVariant() ? "plus" : "normal";
  const body = (await getJson(`${server.replace(/\/+$/, "")}/api/v1/app/android/latest${variant === "plus" ? "?variant=plus" : ""}`)) as { version?: unknown; version_code?: unknown; url?: unknown; variant?: unknown };
  if (typeof body.version !== "string" || typeof body.url !== "string" || typeof body.version_code !== "number") throw new Error("bad_reply");
  if ((variant === "plus" && body.variant !== "plus") || (body.variant !== undefined && body.variant !== variant)) throw new Error("wrong_variant");
  return { version: body.version, url: body.url };
}

/** Newest matching Collect or Collect Plus release with its arm64 APK. */
async function fromGitHub(): Promise<Release> {
  const releases = (await getJson(GITHUB_RELEASES_URL)) as Array<{ tag_name?: string; draft?: boolean; prerelease?: boolean; assets?: Array<{ name?: string; browser_download_url?: string }> }>;
  const plus = isPlusVariant();
  let best: (Release & { code: number }) | undefined;
  for (const release of releases) {
    const version = plus
      ? /^collect-plus-v(\d+\.\d+\.\d+-plus\.\d+)$/.exec(release.tag_name ?? "")?.[1]
      : /^android-v(\d+\.\d+\.\d+)$/.exec(release.tag_name ?? "")?.[1];
    if (!version || release.draft || (!plus && release.prerelease)) continue;
    const code = versionCode(version)! * 100 + Number(/-plus\.(\d+)$/.exec(version)?.[1] ?? 0);
    const asset = release.assets?.find((item) => plus ? /plus.*arm64.*\.apk$/i.test(item.name ?? "") : /^(?!.*plus).*arm64.*\.apk$/i.test(item.name ?? ""));
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
  // Only an https link is ever handed to Linking (no intent:, javascript: or plain http from a bad reply).
  let downloadUrl: URL;
  try {
    downloadUrl = new URL(latest?.url ?? "");
  } catch {
    return { status: "unknown" };
  }
  if (!latest || downloadUrl.protocol !== "https:" || !downloadUrl.hostname) return { status: "unknown" };
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
