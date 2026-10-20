import { createWebWorkspaceTransport } from "../src/workspace/transport.web";
import { cancelCase, chooseInterview, listCasesPath, resolveFlag } from "../src/supervision/api";

const csrf = { header: "X-CSRFToken", token: "csrf-token" };

function jsonResponse(body: unknown) {
  return {
    status: 200,
    ok: true,
    url: "",
    redirected: false,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => body,
    text: async () => JSON.stringify(body),
  };
}

describe("supervision API client", () => {
  const fetchMock = jest.fn();

  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(jsonResponse({ case: { death_id: "D1" } }));
    (global as unknown as { fetch: jest.Mock }).fetch = fetchMock;
  });

  it("builds the list query with only the filters it sets", () => {
    expect(listCasesPath({ state: "", visitNotesOnly: false })).toBe("/api/v1/intake/supervision/cases?");
    expect(listCasesPath({ state: "submitted", visitNotesOnly: true, cursor: "a=b", limit: 200 }))
      .toBe("/api/v1/intake/supervision/cases?state=submitted&visit_note=1&limit=200&cursor=a%3Db");
    expect(listCasesPath({ state: "", visitNotesOnly: false, needsDecision: true, sort: "oldest" }))
      .toBe("/api/v1/intake/supervision/cases?needs_decision=true&sort=oldest");
    expect(listCasesPath({ state: "", visitNotesOnly: false, overdue: true, stuck: true, sort: "newest" }))
      .toBe("/api/v1/intake/supervision/cases?overdue=true&stuck=true");
  });

  it("posts a supervisor action with the CSRF header the transport sends", async () => {
    const request = createWebWorkspaceTransport(csrf);
    await cancelCase(request, "D1", "Moved away");

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/intake/supervision/cases/D1/cancel");
    expect(init.method).toBe("POST");
    expect(init.headers["X-CSRFToken"]).toBe("csrf-token");
    expect(JSON.parse(init.body)).toEqual({ reason: "Moved away" });
  });

  it("posts the confirm flag and the reason code body", async () => {
    const request = createWebWorkspaceTransport(csrf);
    await resolveFlag(request, "D1", true, "");
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ confirm: true, reason: "" });

    await chooseInterview(request, "D1", "DR1", "better_quality");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/v1/intake/supervision/cases/D1/choose-interview");
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({ draft_id: "DR1", reason_code: "better_quality" });
  });
});
