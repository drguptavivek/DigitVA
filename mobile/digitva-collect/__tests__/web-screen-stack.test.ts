import { coveredBySection, navEntries, SECTION_ROUTES, stackRoutePath } from "../src/web/navTabs";

// digitva-hre5: on the web a screen under a later sidebar section leaves the page; Back still reaches it.
const route = (name: string, key = name) => ({ key, name });

test("route names map to their paths", () => {
  expect(stackRoutePath("index")).toBe("/");
  expect(stackRoutePath("coding")).toBe("/coding");
  expect(stackRoutePath("training/index")).toBe("/training");
  expect(stackRoutePath("training/coding/index")).toBe("/training/coding");
  expect(stackRoutePath("training/coding/case")).toBe("/training/coding/case");
});

test("every in-app menu destination counts as a section", () => {
  const all = {
    access: { roles: ["coder", "reviewer", "data_manager", "interview_supervisor", "admin"], is_admin: true, account: { mentor: { member: true } }, training: { areas: ["interview", "coding", "review"] } },
    capabilities: { intake: true, registerDeath: true, registeredDeaths: true, supervision: true, mentoring: true },
  } as unknown as Parameters<typeof navEntries>[0];
  const { primary, more } = navEntries(all);
  const routes = [...primary, ...more].flatMap((entry) => [entry, ...(entry.children ?? [])]).flatMap((entry) => entry.route ? [entry.route] : []);
  expect(routes.length).toBeGreaterThan(10);
  for (const path of routes) expect(SECTION_ROUTES).toContain(path);
});

test("sidebar clicks drop the screens under the new section", () => {
  const stack = [route("index", "a"), route("coding", "b"), route("reviewing", "c"), route("coding", "d")];
  expect(stack.map((r) => coveredBySection(stack, r.key))).toEqual([true, true, true, false]);
});

test("a queue under the case it opened stays mounted, so Back keeps its filters", () => {
  const stack = [route("coding", "q"), route("workspace", "w")];
  expect(coveredBySection(stack, "q")).toBe(false);
  // A section opened from the case drops both.
  const later = [...stack, route("reviewing", "r")];
  expect(coveredBySection(later, "q")).toBe(true);
  expect(coveredBySection(later, "w")).toBe(true);
  expect(coveredBySection(later, "r")).toBe(false);
});

test("an unknown key is never covered", () => {
  expect(coveredBySection([route("coding")], "missing")).toBe(false);
});
