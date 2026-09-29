/**
 * Enrolment QR payload validation.
 *
 * The QR holds `{"v":1,"server":"...","enroll":"<code>","project":"UNSW01"}`
 * (.tasks/2026-09-30-android-collection-app.md, "Provisioning by QR"). The
 * server URL is checked against an allowlist compiled into the build, so a
 * forged QR cannot point the phone at a server that would collect an
 * interviewer's password.
 */

/** Release builds talk to production only, over https. */
const RELEASE_SERVERS = ["https://digitva.causeofdeathindia.com"];
/** Debug builds may also reach a dev server from the emulator or over adb reverse. */
const DEBUG_SERVERS = ["http://10.0.2.2:8051", "http://localhost:8051"];

export function allowedServers(isDev: boolean): string[] {
  return isDev ? [...RELEASE_SERVERS, ...DEBUG_SERVERS] : RELEASE_SERVERS;
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
 * `isDev` is passed in (the app passes `__DEV__`) so tests can check the
 * release allowlist. The server must equal an allowed origin exactly: no
 * path, no other port, no scheme downgrade. Throws EnrolmentError.
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
  const normalized = server.trim().replace(/\/+$/, "").toLowerCase();
  if (!allowedServers(isDev).includes(normalized)) {
    throw new EnrolmentError("errServerNotAllowed");
  }
  return { server: normalized, code: enroll, project };
}
