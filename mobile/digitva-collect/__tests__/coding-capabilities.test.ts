import { canUseOfflineCoding, offlineCodingProjectIds } from "../src/codingCapabilities";
import type { AccessSummary } from "../src/api";

const project = (projectId: string, enabled: boolean, grant: Partial<AccessSummary["projects"][number]["grants"][number]> = {}) => ({
  project_id: projectId,
  project_name: projectId,
  has_tree: false,
  self_coding: { enabled },
  grants: [{ role: "coder", scope: "project", active: true, source: "assigned" as const, codes: true, ...grant }],
  sites: [],
  actions: { interview: [], register_death: [] },
});

const access = (...projects: AccessSummary["projects"]): AccessSummary => ({
  user: { user_id: "u1", name: "Coder" },
  is_admin: false,
  roles: ["coder"],
  demo_coding: { available: false, project_ids: [] },
  projects,
});

describe("offline coding capability", () => {
  it("requires self-coding and an active codes-enabled coder grant in the same project", () => {
    expect(offlineCodingProjectIds(access(project("same", true)))).toEqual(["same"]);
    expect(offlineCodingProjectIds(access(project("cross", false), project("self", true, { codes: false })))).toEqual([]);
    expect(offlineCodingProjectIds(access(project("inactive", true, { active: false })))).toEqual([]);
    expect(offlineCodingProjectIds(access(project("tester", true, { role: "coding_tester" })))).toEqual([]);
  });

  it("treats missing cached access as unavailable and standalone as local self-coding", () => {
    expect(canUseOfflineCoding({})).toBe(false);
    expect(canUseOfflineCoding({ offline_coding_access: ["same"] }, "other")).toBe(false);
    expect(canUseOfflineCoding({ standalone: true })).toBe(true);
  });

  it("fails closed for revoked or otherwise unusable cached accounts", () => {
    for (const flag of ["needs_sign_in", "access_removed", "access_blocked", "terms_required", "signed_out"] as const) {
      expect(canUseOfflineCoding({ offline_coding_access: ["same"], [flag]: true }, "same")).toBe(false);
    }
  });

  it("allows a demo account only from its own refreshed access summary", () => {
    const demo = offlineCodingProjectIds(access(project("demo-project", true)));
    expect(canUseOfflineCoding({ offline_coding_access: demo }, "demo-project")).toBe(true);
    expect(canUseOfflineCoding({ offline_coding_access: demo }, "active-project")).toBe(false);
  });
});
