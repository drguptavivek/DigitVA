import { loginRecoveryUrl } from "../src/web/loginRecovery";

describe("browser login recovery", () => {
  it("preserves the current app route and query for ordinary sign-in", () => {
    expect(
      loginRecoveryUrl("/vaauth/valogin?next=%2Fapp%2F", undefined, "https://digitva.test/app/collection?project=P1")
    ).toBe("/vaauth/valogin?next=%2Fapp%2Fcollection%3Fproject%3DP1");
  });

  it("falls back to the app root outside the app route boundary", () => {
    expect(loginRecoveryUrl("/vaauth/valogin", undefined, "https://digitva.test/application")).toBe("/vaauth/valogin?next=%2Fapp%2F");
  });

  it("rejects external and unsafe login links", () => {
    expect(loginRecoveryUrl("https://evil.test/login", undefined, "https://digitva.test/app/")).toBe("/");
    expect(loginRecoveryUrl("javascript:alert(1)", undefined, "https://digitva.test/app/")).toBe("/");
    expect(loginRecoveryUrl("//evil.test/login", undefined, "https://digitva.test/app/")).toBe("/");
    expect(loginRecoveryUrl("/unexpected-route", undefined, "https://digitva.test/app/")).toBe("/");
  });

  it("uses the fixed internal terms action", () => {
    expect(loginRecoveryUrl("/profile/password?next=%2Fapp%2F", "terms_required", "https://digitva.test/app/collection")).toBe(
      "/profile/force-password-change"
    );
  });
});
