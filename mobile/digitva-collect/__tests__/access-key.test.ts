import { stableAccessJson } from "../src/accessKey";

test("the access key ignores the per-call server_time stamp but not project_today or real changes", () => {
  const at = (time: string, today: string, role = "coder") => ({
    roles: [role], projects: [{ project_id: "P", server_time: time, project_today: today, grants: [{ role }] }],
  });
  expect(stableAccessJson(at("2026-11-07T01:00:00.000001Z", "2026-11-07"))).toBe(stableAccessJson(at("2026-11-07T01:00:09.5Z", "2026-11-07")));
  expect(stableAccessJson(at("t", "2026-11-07"))).not.toBe(stableAccessJson(at("t", "2026-11-08")));
  expect(stableAccessJson(at("t", "d"))).not.toBe(stableAccessJson(at("t", "d", "reviewer")));
  expect(stableAccessJson(at("t", "d"))).toContain("coder");
});
