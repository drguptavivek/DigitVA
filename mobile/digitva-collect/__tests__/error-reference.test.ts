import { ApiError, maskApiPath, requestJson } from "../src/api";
import { errorReference, errorText } from "../src/ui";

describe("maskApiPath", () => {
  it("drops query and masks id-like segments", () => {
    expect(maskApiPath("/api/v1/cases/123/detail?token=abc")).toBe("/api/v1/cases/:id/detail");
    expect(maskApiPath("/api/v1/drafts/3f2b8c1e-4d5a-4b6c-8d7e-9f0a1b2c3d4e/submit")).toBe("/api/v1/drafts/:id/submit");
    expect(maskApiPath("/api/v1/x/deadbeef01")).toBe("/api/v1/x/:id");
    expect(maskApiPath("/api/v1/me/access")).toBe("/api/v1/me/access");
  });
});

describe("errorReference", () => {
  it("describes an ApiError with code, method and masked path", () => {
    const e = new ApiError(502, "bad_gateway");
    e.path = "/api/v1/me/access";
    expect(errorReference(e)).toMatch(/^Ref: HTTP 502 bad_gateway GET \/api\/v1\/me\/access · \d\d:\d\dZ · v\S+$/);
  });
  it("labels network and unknown failures", () => {
    expect(errorReference(new TypeError("Network request failed"))).toMatch(/^Ref: network · /);
    expect(errorReference("boom")).toMatch(/^Ref: unknown · /);
  });
  it("masks quoted values and digit runs in generic errors", () => {
    const ref = errorReference(new Error('no such column "Asha Devi" row 123456'));
    expect(ref).toContain("Error no such column");
    expect(ref).not.toContain("Asha");
    expect(ref).not.toContain("123456");
  });
  it("keeps a native function name and the cause", () => {
    const ref = errorReference(new Error("Call to function 'NativeDatabase.prepareAsync' has been rejected.\n→ Caused by: Error code 5: database is locked"));
    expect(ref).toContain("'NativeDatabase.prepareAsync' has been rejected. → Caused by: Error code 5: database is locked");
  });
  it("masks quoted free text, file paths and long messages", () => {
    expect(errorReference(new Error("bad 'Asha Devi' value"))).toContain("bad '…' value");
    const path = errorReference(new Error("open file:///data/user/0/app/Asha_1.json failed; /data/user/0/x/y.db"));
    expect(path).not.toContain("Asha");
    expect(path).not.toContain("user/0");
    expect(path).toContain("file:… failed; file:…");
    const long = errorReference(new Error("x".repeat(500)));
    expect(long.split(" · ")[0].length).toBeLessThanOrEqual("Ref: Error ".length + 160);
  });
  it("is appended to the generic fallback only", () => {
    expect(errorText(new ApiError(500, undefined))).toContain("Ref: HTTP 500");
    expect(errorText(new ApiError(429, undefined))).not.toContain("Ref:");
  });
});

describe("requestJson route", () => {
  it("records method and masked route on an HTTP failure", async () => {
    global.fetch = jest.fn(async () => ({
      status: 502, ok: false, redirected: false, type: "basic",
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => ({ code: "bad_gateway" }),
    })) as unknown as typeof fetch;
    const error = await requestJson("", "/api/v1/cases/42?q=secret", { method: "POST" }).catch((e) => e);
    expect(error).toMatchObject({ status: 502, code: "bad_gateway", method: "POST", path: "/api/v1/cases/:id" });
  });
});
