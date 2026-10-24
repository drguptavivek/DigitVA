import { requestClientJson, runAsBackground } from "../src/api";

function response(body: unknown, status = 200): Response {
  return {
    status, ok: status >= 200 && status < 300, redirected: false,
    headers: { get: (name: string) => (name.toLowerCase() === "content-type" ? "application/json" : null) },
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}
const headersOf = (fetchMock: jest.SpyInstance, call: number) => fetchMock.mock.calls[call][1]?.headers as Record<string, string>;

afterEach(() => jest.restoreAllMocks());

describe("X-DigitVA-Background", () => {
  it("is sent only for background requests", async () => {
    const fetchMock = jest.spyOn(globalThis, "fetch").mockImplementation(async () => response({ ok: true }));
    await requestClientJson("/api/v1/me/notifications?after=0", { background: true });
    await runAsBackground(() => requestClientJson("/api/v1/intake/cases"));
    await requestClientJson("/api/v1/me/access");
    expect(headersOf(fetchMock, 0)["X-DigitVA-Background"]).toBe("1");
    expect(headersOf(fetchMock, 1)["X-DigitVA-Background"]).toBe("1");
    expect(headersOf(fetchMock, 2)["X-DigitVA-Background"]).toBeUndefined();
  });

  it("a session_idle refusal raises digitva-session-idle", async () => {
    jest.spyOn(globalThis, "fetch").mockResolvedValue(response({ code: "session_idle" }, 401));
    const dispatch = jest.fn();
    Object.defineProperty(window, "dispatchEvent", { configurable: true, value: dispatch });
    await expect(requestClientJson("/api/v1/intake/cases")).rejects.toMatchObject({ status: 401 });
    expect(dispatch.mock.calls[0][0].type).toBe("digitva-session-idle");
  });
});
