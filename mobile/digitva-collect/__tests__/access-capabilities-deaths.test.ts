import { accessCapabilities, type AccessSummary } from "../src/api";

const summary = (projects: Array<{ supervises_deaths?: boolean }>) => ({
  user: { user_id: "u", name: "n" }, is_admin: false, roles: ["interview_supervisor"],
  demo_coding: { available: false, project_ids: [] },
  projects: projects.map((p) => ({ actions: { interview: [], register_death: [] }, ...p })),
}) as unknown as AccessSummary;

test("supervision capability follows the server's supervises_deaths, not the role alone", () => {
  expect(accessCapabilities(summary([{ supervises_deaths: false }])).supervision).toBe(false);
  expect(accessCapabilities(summary([{}])).supervision).toBe(false);
  expect(accessCapabilities(summary([{ supervises_deaths: false }, { supervises_deaths: true }])).supervision).toBe(true);
});
