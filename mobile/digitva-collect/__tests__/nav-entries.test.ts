import { navEntries } from "../src/web/navTabs";

type Fixture = { roles?: string[]; is_admin?: boolean; mentor?: { member?: boolean; admin_of?: string[] }; caps?: Record<string, boolean> };

const boot = ({ roles = [], is_admin = false, mentor, caps = {} }: Fixture) => ({
  access: { roles, is_admin, ...(mentor ? { account: { mentor } } : {}) },
  capabilities: { intake: false, registerDeath: false, registeredDeaths: false, supervision: false, ...caps },
}) as unknown as Parameters<typeof navEntries>[0];

/** Every destination of the new menu, the death list and form counted as one screen (it switches views in place). */
const reachable = (fixture: Fixture) => {
  const { primary, more } = navEntries(boot(fixture));
  return new Set([...primary, ...more].map((entry) => entry.route ?? entry.serverPath ?? entry.href));
};

/**
 * What each role reached before the owner's menu, written out by hand from the old sidebar (common.tsx), the old
 * header tabs (roleScreens + serverScreens) and the home screen's Admin console. Every user also had Organization,
 * Settings and Sign out.
 */
const BEFORE: Array<[string, Fixture, string[]]> = [
  ["coder", { roles: ["coder"] }, ["/coding"]],
  ["coding tester", { roles: ["coding_tester"] }, ["/coding"]],
  ["reviewer", { roles: ["reviewer"] }, ["/reviewing"]],
  ["interviewer", { roles: ["interviewer"], caps: { intake: true } }, ["/collection"]],
  ["death reporter (register only)", { roles: ["death_reporter"], caps: { registerDeath: true } }, ["/death-registration"]],
  ["death reporter (my list only)", { roles: ["death_reporter"], caps: { registeredDeaths: true } }, ["/death-registration"]],
  ["interview supervisor", { roles: ["interview_supervisor"], caps: { supervision: true } }, ["/supervision"]],
  ["data manager", { roles: ["data_manager"], caps: { supervision: true } }, ["/supervision", "/area/", "/data-management/"]],
  ["mentor member", { mentor: { member: true } }, ["/mentoring"]],
  ["mentor institute admin", { mentor: { admin_of: ["I1"] } }, ["/mentoring"]],
  ["mentoring capability", { caps: { mentoring: true } }, ["/mentoring"]],
  ["platform admin", { is_admin: true }, ["/admin/"]],
  ["admin role", { roles: ["admin"] }, ["/admin/"]],
  ["no role", {}, []],
];

test.each(BEFORE)("%s keeps every destination it had", (_name, fixture, had) => {
  const now = reachable(fixture);
  for (const route of [...had, "/organization", "/settings", "/"]) expect(now).toContain(route);
});

test.each(BEFORE)("%s gains nothing beyond its roles but Home and the public website", (_name, fixture, had) => {
  expect([...reachable(fixture)].sort()).toEqual([...had, "/organization", "/settings", "/", "/vaindex"].sort());
});

test("order: the owner's primary items, then More in the owner's order", () => {
  const all = boot({
    roles: ["coder", "reviewer", "data_manager", "interview_supervisor"],
    is_admin: true,
    mentor: { member: true },
    caps: { intake: true, registerDeath: true, registeredDeaths: true, supervision: true },
  });
  const { primary, more } = navEntries(all);
  expect(primary.map((entry) => entry.labelKey)).toEqual(["home", "navDeaths", "navVaInterview", "navVaCode", "navVaReview", "navStatistics"]);
  expect(more.map((entry) => entry.labelKey)).toEqual(["navOrg", "navSettings", "navWebsite", "supervisionTitle", "navDataManagement", "navMentoring", "homeAdminConsole"]);
});

test("Deaths opens the deaths list for a user who interviews or reports deaths", () => {
  const deaths = (caps: Record<string, boolean>) => navEntries(boot({ caps })).primary.find((entry) => entry.key === "/death-registration");
  expect(deaths({ registerDeath: true, registeredDeaths: true })?.params).toEqual({ view: "mine" });
  expect(deaths({ registeredDeaths: true })?.params).toEqual({ view: "mine" });
  expect(deaths({ registerDeath: true, intake: true })?.params).toEqual({ view: "mine" });
  expect(deaths({ registerDeath: true })?.params).toBeUndefined();
  expect(deaths({})).toBeUndefined();
});
