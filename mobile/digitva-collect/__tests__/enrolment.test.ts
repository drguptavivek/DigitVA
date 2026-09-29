import { parseEnrolmentQr } from "../src/enrolment";

const qr = (server: string, extra: Record<string, unknown> = {}) =>
  JSON.stringify({ v: 1, server, enroll: "AbCdEf123456_-x", project: "UNSW01", ...extra });

describe("parseEnrolmentQr", () => {
  it("accepts the production host in release and debug builds", () => {
    for (const isDev of [false, true]) {
      expect(parseEnrolmentQr(qr("https://digitva.causeofdeathindia.com/"), isDev)).toEqual({
        server: "https://digitva.causeofdeathindia.com",
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
