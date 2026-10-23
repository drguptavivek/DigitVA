import { acceptedServerOrigin, DEFAULT_RELEASE_SERVER, EnrolmentError, normalizeHttpsOrigin, parseEnrolmentQr, parseScannedQr } from "../src/enrolment";

const releaseOrigin = new URL(
  process.env.EXPO_PUBLIC_API_BASE_URL || DEFAULT_RELEASE_SERVER
).origin.toLowerCase();

const qr = (server: string, extra: Record<string, unknown> = {}) =>
  JSON.stringify({ v: 1, server, enroll: "AbCdEf123456_-x", project: "UNSW01", ...extra });

describe("acceptedServerOrigin", () => {
  it.each([
    ["https://digitva.causeofdeathindia.com", "https://digitva.causeofdeathindia.com"],
    ["https://digitvav3.causeofdeathindia.com/", "https://digitvav3.causeofdeathindia.com"],
    ["https://causeofdeathindia.com", "https://causeofdeathindia.com"],
    ["HTTPS://DigitVAv3.CauseOfDeathIndia.COM", "https://digitvav3.causeofdeathindia.com"],
    ["https://a.b-c.causeofdeathindia.com:443", "https://a.b-c.causeofdeathindia.com"],
  ])("accepts %s in release and debug builds", (raw, origin) => {
    expect(acceptedServerOrigin(raw, false)).toBe(origin);
    expect(acceptedServerOrigin(raw, true)).toBe(origin);
  });

  it.each([
    "https://evilcauseofdeathindia.com",
    "https://causeofdeathindia.com.evil.io",
    "https://digitva.causeofdeathindia.com.evil.io",
    "https://user:pass@digitva.causeofdeathindia.com",
    "https://evil.io@digitva.causeofdeathindia.com",
    "https://digitva.causeofdeathindia.com@evil.io",
    "https://digitva.causeofdeathindia.com:8443",
    "https://digitva.causeofdeathindia.com/api",
    "https://digitva.causeofdeathindia.com?x=1",
    "https://digitva.causeofdeathindia.com#x",
    "http://digitva.causeofdeathindia.com",
    "https://causeofdeathindia.com.",
    "https://.causeofdeathindia.com",
    "https://digitva..causeofdeathindia.com",
    "https://digitva.causeofdeathіndia.com", // Cyrillic і
    "https://digitva.cаuseofdeathindia.com", // Cyrillic а
    "https://xn--causeofdeathndia-yxc.com",
    "ftp://digitva.causeofdeathindia.com",
    "https://evil.example",
    "digitva.causeofdeathindia.com",
    "",
  ])("refuses %s even in debug builds", (raw) => {
    expect(acceptedServerOrigin(raw, false)).toBeNull();
    expect(acceptedServerOrigin(raw, true)).toBeNull();
  });

  it("accepts the dev origins only in debug builds", () => {
    for (const raw of ["http://10.0.2.2:8051", "http://localhost:8051/"]) {
      expect(acceptedServerOrigin(raw, false)).toBeNull();
      expect(acceptedServerOrigin(raw, true)).toBe(raw.replace(/\/$/, ""));
    }
    expect(acceptedServerOrigin("http://localhost:8052", true)).toBeNull();
    expect(acceptedServerOrigin("https://localhost:8051", true)).toBeNull();
  });
});

describe("parseEnrolmentQr", () => {
  it("normalizes only exact HTTPS origins", () => {
    expect(normalizeHttpsOrigin("HTTPS://DigitVAv3.CauseOfDeathIndia.com/")).toBe(
      "https://digitvav3.causeofdeathindia.com"
    );
    for (const value of [
      "http://digitvav3.causeofdeathindia.com",
      "https://digitvav3.causeofdeathindia.com/api",
      "https://user:pass@digitvav3.causeofdeathindia.com",
      "https://digitvav3.causeofdeathindia.com?x=1",
      "https://digitvav3.causeofdeathindia.com#fragment",
    ]) {
      expect(normalizeHttpsOrigin(value)).toBeNull();
    }
  });

  it("accepts staging from a release build", () => {
    expect(parseEnrolmentQr(qr("https://digitvav3.causeofdeathindia.com"), false).server).toBe(
      "https://digitvav3.causeofdeathindia.com"
    );
  });

  it("accepts the configured production host in release and debug builds", () => {
    for (const isDev of [false, true]) {
      expect(parseEnrolmentQr(qr(`${releaseOrigin}/`), isDev)).toEqual({
        server: releaseOrigin,
        code: "AbCdEf123456_-x",
        project: "UNSW01"
      });
    }
  });

  it("accepts the emulator dev hosts only in debug builds", () => {
    expect(parseEnrolmentQr(qr("http://10.0.2.2:8051"), true).server).toBe("http://10.0.2.2:8051");
    expect(parseEnrolmentQr(qr("http://localhost:8051"), true).server).toBe("http://localhost:8051");
    expect(() => parseEnrolmentQr(qr("http://10.0.2.2:8051"), false)).toThrow("errServerNotAllowed");
    expect(() => parseEnrolmentQr(qr("http://localhost:8051"), false)).toThrow("errServerNotAllowed");
  });

  it("rejects http for the production host and look-alike hosts", () => {
    for (const server of [
      "http://digitva.causeofdeathindia.com",
      "https://digitva.causeofdeathindia.com.evil.example",
      "https://evilcauseofdeathindia.com",
      "https://digitva.causeofdeathindia.com/api",
      "https://evil.example"
    ]) {
      expect(() => parseEnrolmentQr(qr(server), true)).toThrow("errServerNotAllowed");
    }
  });

  it("rejects bad JSON and the wrong shape", () => {
    for (const raw of [
      "not json",
      "",
      "[]",
      "null",
      qr("https://digitva.causeofdeathindia.com", { v: 2 }),
      qr("https://digitva.causeofdeathindia.com", { enroll: "" }),
      qr("https://digitva.causeofdeathindia.com", { project: "../x" }),
      JSON.stringify({ v: 1, server: "https://digitva.causeofdeathindia.com", project: "UNSW01" })
    ]) {
      expect(() => parseEnrolmentQr(raw, true)).toThrow("errBadQr");
    }
  });
});

describe("parseScannedQr", () => {
  const SERVER = "https://digitva.causeofdeathindia.com";
  const TOKEN = "SignInTokenSignInTokenSignInToken123";
  const signIn = (extra: Record<string, unknown> = {}) => JSON.stringify({ v: 1, server: SERVER, sign_in: TOKEN, ...extra });

  it("reads an enrolment QR as before, tagged enroll", () => {
    expect(parseScannedQr(qr(SERVER), false)).toEqual({ kind: "enroll", server: SERVER, code: "AbCdEf123456_-x", project: "UNSW01" });
  });

  it("reads a sign-in QR", () => {
    expect(parseScannedQr(signIn(), false)).toEqual({ kind: "sign_in", server: SERVER, token: TOKEN });
  });

  it("applies the same server rule to a sign-in QR", () => {
    for (const server of ["https://evilcauseofdeathindia.com", "http://digitva.causeofdeathindia.com", "https://digitva.causeofdeathindia.com/x"]) {
      expect(() => parseScannedQr(signIn({ server }), false)).toThrow(expect.objectContaining({ key: "errServerNotAllowed" }));
    }
    expect(() => parseScannedQr(signIn({ server: "http://localhost:8051" }), false)).toThrow(EnrolmentError);
    expect(parseScannedQr(signIn({ server: "http://localhost:8051" }), true).server).toBe("http://localhost:8051");
  });

  it.each([
    ["not json", "nope"],
    ["wrong version", signIn({ v: 2 })],
    ["token too short", signIn({ sign_in: "short" })],
    ["token with bad characters", signIn({ sign_in: "bad token bad token bad token!" })],
    ["token not a string", signIn({ sign_in: 12345678901234567890 })],
    ["no server", JSON.stringify({ v: 1, sign_in: TOKEN })],
  ])("rejects a bad sign-in QR: %s", (_name, raw) => {
    expect(() => parseScannedQr(raw, false)).toThrow(expect.objectContaining({ key: "errBadQr" }));
  });

  it("never puts the token in the error", () => {
    try {
      parseScannedQr(signIn({ server: "https://evil.io" }), false);
    } catch (caught) {
      expect(String(caught) + JSON.stringify(caught)).not.toContain(TOKEN);
    }
  });
});
