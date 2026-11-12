import { codingServerStatusText } from "../src/workspace/QueueScreen";
import en from "../src/strings/en.json";
import hi from "../src/strings/hi.json";

describe("codingServerStatusText", () => {
  it("has words for the refusals the old server and self-coding-off send", () => {
    for (const code of ["coding_conflict", "self_coding_required"]) {
      const text = codingServerStatusText({ server_status: "refused", server_code: code });
      expect(text).toContain(en[`codingRefused_${code}` as keyof typeof en]);
      expect(text).not.toContain(en.codingRefused_unknown.slice(0, 10));
      expect(hi[`codingRefused_${code}` as keyof typeof hi]).toBeTruthy();
    }
  });
  it("tells the coder to code again with new data when the interview changed after coding", () => {
    expect(codingServerStatusText({ server_status: "refused", server_code: "coded_version_superseded" })).toBe(en.codingStaleRecode);
  });
  it("shows the recode notice when the server flags an upstream change on a case the phone never coded", () => {
    expect(codingServerStatusText({ needs_recode: true })).toBe(en.codingStaleRecode);
    expect(codingServerStatusText({ needs_recode: false })).toBeNull();
    expect(codingServerStatusText({})).toBeNull();
  });
});
