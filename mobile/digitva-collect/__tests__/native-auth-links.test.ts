import {
  mobileDigitsFromInput,
  nativeAuthUrl,
  NATIVE_AUTH_PATHS,
  normalizeMobileIdentifier
} from "../src/nativeAuthLinks";

describe("native sign-in identifier and server links", () => {
  it("normalizes India mobile pastes to the API identifier", () => {
    expect(mobileDigitsFromInput("+91 987 654 3210")).toBe("9876543210");
    expect(mobileDigitsFromInput("91-9876543210")).toBe("9876543210");
    expect(normalizeMobileIdentifier("+91 987 654 3210")).toBe("+919876543210");
    expect(normalizeMobileIdentifier("987654321")).toBeUndefined();
    expect(normalizeMobileIdentifier("1234567890")).toBeUndefined();
    expect(normalizeMobileIdentifier("98765432101")).toBeUndefined();
  });

  it("only builds handoff links for the enrolled server allowlist", () => {
    expect(nativeAuthUrl("https://digitva.causeofdeathindia.com/", NATIVE_AUTH_PATHS.redeemCode, false)).toBe(
      "https://digitva.causeofdeathindia.com/vaauth/valogin/code"
    );
    expect(nativeAuthUrl("http://localhost:8051", NATIVE_AUTH_PATHS.forgotPassword, true)).toBe(
      "http://localhost:8051/vaauth/forgot-password"
    );
    expect(() => nativeAuthUrl("http://localhost:8051", NATIVE_AUTH_PATHS.signIn, false)).toThrow(
      "server_not_allowed"
    );
    expect(() => nativeAuthUrl("https://evil.example", NATIVE_AUTH_PATHS.signIn, true)).toThrow(
      "server_not_allowed"
    );
  });
});
