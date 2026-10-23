/**
 * Enrolment QR payload validation.
 *
 * The QR holds `{"v":1,"server":"...","enroll":"<code>","project":"UNSW01"}`
 * (.tasks/2026-09-30-android-collection-app.md, "Provisioning by QR"). The
 * server is checked against a rule compiled into the build, so a forged QR
 * cannot point the phone at a server that would collect an interviewer's
 * password: an https origin on the organisation's own domain (production,
 * staging and any other host under it), shown to the user before the code is
 * redeemed. docs/policy/mobile-sign-in.md holds the rule.
 */

/** The one domain whose https hosts a release build will enrol on. */
export const ENROLMENT_DOMAIN = "causeofdeathindia.com";
/** Production origin; the release build's documented default API origin. */
export const DEFAULT_RELEASE_SERVER = `https://digitva.${ENROLMENT_DOMAIN}`;
/**
 * The public demo's origin (docs/policy/public-demo.md section 10), compiled
 * in: "Try the demo" enrols only here, so a release build never sends a demo
 * username or password anywhere else.
 */
export const DEMO_SERVER = `https://demo.${ENROLMENT_DOMAIN}`;
/**
 * Debug builds may also reach a dev server from the emulator or over adb
 * reverse. Empty in release (`__DEV__` is false there), so the strings never
 * enter a release bundle and scripts/verify-android-release.sh can reject them.
 */
const DEBUG_SERVERS = __DEV__ ? ["http://10.0.2.2:8051", "http://localhost:8051"] : [];
/** One DNS label: ASCII letters, digits and inner hyphens. Punycoded (xn--) labels stay ASCII. */
const LABEL = /^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/;

/**
 * Parse `raw` as a bare origin. API paths, credentials, query and fragment
 * are not valid server identities for enrolment and are rejected.
 */
function parseBareOrigin(raw: string): URL | null {
  try {
    const url = new URL(raw.trim());
    if (
      !url.hostname ||
      url.username ||
      url.password ||
      (url.pathname !== "" && url.pathname !== "/") ||
      url.search ||
      url.hash
    ) {
      return null;
    }
    return url;
  } catch {
    return null;
  }
}

/** Return an exact HTTPS origin, or null. */
export function normalizeHttpsOrigin(raw: string): string | null {
  const url = parseBareOrigin(raw);
  return url && url.protocol === "https:" ? url.origin.toLowerCase() : null;
}

/** EXPO_PUBLIC_API_BASE_URL, compiled in: one more exact origin a build accepts. */
const compiledServer = normalizeHttpsOrigin(process.env.EXPO_PUBLIC_API_BASE_URL ?? "");

/** https, default port, and every label of the host valid ASCII ending in ENROLMENT_DOMAIN. */
function isDomainOrigin(url: URL): boolean {
  if (url.protocol !== "https:" || url.port !== "") return false;
  const host = url.hostname.toLowerCase();
  if (host !== ENROLMENT_DOMAIN && !host.endsWith(`.${ENROLMENT_DOMAIN}`)) return false;
  return host.split(".").every((label) => LABEL.test(label));
}

/**
 * The normalised origin when `raw` names a server this build may use, else
 * null. `isDev` (the app passes `__DEV__`) adds the exact debug origins.
 * Look-alikes (`evilcauseofdeathindia.com`, `causeofdeathindia.com.evil.io`),
 * Unicode homoglyphs (they parse to `xn--` labels that do not match), http,
 * other ports, userinfo, paths, query and fragment are all refused.
 */
export function acceptedServerOrigin(raw: string, isDev: boolean): string | null {
  const url = parseBareOrigin(raw);
  if (!url) return null;
  const origin = url.origin.toLowerCase();
  if (isDev && DEBUG_SERVERS.includes(origin)) return origin;
  if (origin === compiledServer || isDomainOrigin(url)) return origin;
  return null;
}

/**
 * The origin "Try the demo" talks to: DEMO_SERVER, except that a debug build
 * (`isDev`) may name a local dev server in `override` (EXPO_PUBLIC_DEMO_SERVER),
 * which must pass acceptedServerOrigin. A release build ignores `override`.
 */
export function demoServerOrigin(isDev: boolean, override?: string): string {
  const origin = isDev && override ? acceptedServerOrigin(override, true) : null;
  return origin ?? DEMO_SERVER;
}

/** Whether `server` (an enrolled device's origin) is the demo server this build uses. */
export function isDemoServer(server: string | undefined, isDev: boolean, override?: string): boolean {
  return !!server && server.toLowerCase() === demoServerOrigin(isDev, override);
}

export interface EnrolmentPayload {
  server: string;
  code: string;
  project: string;
}

/** `key` names the UI string (see src/strings) the screen shows. */
export class EnrolmentError extends Error {
  constructor(public key: "errBadQr" | "errServerNotAllowed") {
    super(key);
    this.name = "EnrolmentError";
  }
}

/**
 * Parse and validate a scanned or pasted QR payload.
 *
 * `isDev` is passed in so tests can check the release rule. The server must
 * pass acceptedServerOrigin. Throws EnrolmentError.
 */
export function parseEnrolmentQr(raw: string, isDev: boolean): EnrolmentPayload {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new EnrolmentError("errBadQr");
  }
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new EnrolmentError("errBadQr");
  }
  const { v, server, enroll, project } = value as Record<string, unknown>;
  if (v !== 1 || typeof server !== "string" || typeof enroll !== "string" || typeof project !== "string") {
    throw new EnrolmentError("errBadQr");
  }
  if (!/^[A-Za-z0-9_-]{8,256}$/.test(enroll) || !/^[A-Za-z0-9_-]{1,64}$/.test(project)) {
    throw new EnrolmentError("errBadQr");
  }
  const origin = acceptedServerOrigin(server, isDev);
  if (!origin) throw new EnrolmentError("errServerNotAllowed");
  return { server: origin, code: enroll, project };
}

/** A scanned QR: the device-only enrolment code, or a sign-in token (docs/policy/mobile-sign-in.md section 8). */
export type ScannedQr =
  | ({ kind: "enroll" } & EnrolmentPayload)
  | { kind: "sign_in"; server: string; token: string };

/**
 * Parse a scanned or pasted QR of either kind. A payload with a `sign_in`
 * field is the sign-in QR `{"v":1,"server":...,"sign_in":<token>}`; anything
 * else must be an enrolment QR. The server rule is the same for both.
 * Throws EnrolmentError; the token is never put in a message.
 */
export function parseScannedQr(raw: string, isDev: boolean): ScannedQr {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    throw new EnrolmentError("errBadQr");
  }
  if (typeof value !== "object" || value === null || !("sign_in" in value)) {
    return { kind: "enroll", ...parseEnrolmentQr(raw, isDev) };
  }
  const { v, server, sign_in: token } = value as Record<string, unknown>;
  if (v !== 1 || typeof server !== "string" || typeof token !== "string" || !/^[A-Za-z0-9_-]{16,256}$/.test(token)) {
    throw new EnrolmentError("errBadQr");
  }
  const origin = acceptedServerOrigin(server, isDev);
  if (!origin) throw new EnrolmentError("errServerNotAllowed");
  return { kind: "sign_in", server: origin, token };
}
