import { sameBootstrap } from "../src/AppState.web";
import type { ClientBootstrap } from "../src/client/api";

// digitva-te2a: Safari re-reads /me/access on every pageshow/visibilitychange. A new server_time
// alone must not count as a new session, or the open interview re-initialises and loses its answers.
const bootstrap = (serverTime: string, csrf = "a", role = "data_collector") => ({
  csrf,
  user: { user_id: "u1" },
  access: { projects: [{ project_id: "P1", server_time: serverTime, project_today: "2026-11-18", roles: [role] }] },
}) as unknown as ClientBootstrap;

test("a re-read that differs only by server_time and csrf is the same session", () => {
  expect(sameBootstrap(bootstrap("2026-11-18T06:56:34.862Z"), bootstrap("2026-11-18T06:57:01.000Z", "b"))).toBe(true);
});

test("a real access change is a new session", () => {
  expect(sameBootstrap(bootstrap("t"), bootstrap("t", "a", "reviewer"))).toBe(false);
  expect(sameBootstrap(undefined, bootstrap("t"))).toBe(false);
});
