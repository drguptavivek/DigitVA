import {
  createNotificationPollGate,
  drainNotificationPages,
  NotificationPollError,
  parseNotificationPage
} from "../src/notificationPoll";

const notification = (id: number, fields: Record<string, unknown> = {}) => ({
  id,
  kind: "revision_requested",
  created_at: "2026-10-05T09:30:00+00:00",
  project_id: "ABC01",
  death_id: null,
  draft_id: null,
  va_sid: null,
  ...fields
});

const page = (notifications: unknown[], next_cursor?: number) => {
  const last = notifications[notifications.length - 1];
  const lastId = typeof last === "object" && last !== null && "id" in last ? last.id : undefined;
  return { notifications, next_cursor: next_cursor ?? (typeof lastId === "number" ? lastId : 0) };
};

describe("parseNotificationPage", () => {
  it("accepts an empty page and a safe cursor rewind after restore", () => {
    expect(parseNotificationPage(page([], 8), 12)).toEqual({
      nextCursor: 8,
      nonEmpty: false,
      hasMore: false
    });
  });

  it("accepts known and unknown kinds without retaining notification rows", () => {
    expect(parseNotificationPage(page([
      notification(2), notification(3, { kind: "future_notification_kind" })
    ]), 1)).toEqual({ nextCursor: 3, nonEmpty: true, hasMore: false });
  });

  it.each([
    ["malformed payload", null],
    ["missing notifications", { next_cursor: 0 }],
    ["non-array notifications", { notifications: {}, next_cursor: 0 }],
    ["negative cursor", page([], -1)],
    ["unsafe cursor", page([], Number.MAX_SAFE_INTEGER + 1)],
    ["more than one page", page(Array.from({ length: 101 }, (_, index) => notification(index + 1)))],
    ["malformed notification", page([null])],
    ["unsafe notification id", page([notification(Number.MAX_SAFE_INTEGER + 1)])],
    ["blank kind", page([notification(1, { kind: "   " })])],
    ["timestamp without offset", page([notification(1, { created_at: "2026-10-05T09:30:00" })])],
    ["invalid calendar date", page([notification(1, { created_at: "2026-02-30T09:30:00+00:00" })])],
    ["invalid offset", page([notification(1, { created_at: "2026-10-05T09:30:00+99:00" })])],
    ["invalid timestamp", page([notification(1, { created_at: "not a timestamp+00:00" })])],
    ["invalid nullable UUID", page([notification(1, { death_id: "not-a-uuid" })])],
    ["project id beyond backend column", page([notification(1, { project_id: "TOOLONG" })])],
    ["kind beyond backend column", page([notification(1, { kind: "k".repeat(33) })])],
    ["va sid beyond backend column", page([notification(1, { va_sid: "s".repeat(65) })])],
    ["cursor that skips the last row", page([notification(1)], 2)]
  ])("rejects %s", (_description, payload) => {
    expect(() => parseNotificationPage(payload, 0)).toThrow(NotificationPollError);
  });

  it.each([
    [[notification(2), notification(1)]],
    [[notification(1), notification(1)]]
  ])("rejects out-of-order or duplicate ids", (notifications) => {
    expect(() => parseNotificationPage(page(notifications), 0)).toThrow(NotificationPollError);
  });

  it("requires every returned id to be greater than the requested cursor", () => {
    expect(() => parseNotificationPage(page([notification(4)]), 4)).toThrow(NotificationPollError);
  });
});

describe("drainNotificationPages", () => {
  it("continues immediately after a full page and stops at the empty page", async () => {
    const request = jest.fn()
      .mockResolvedValueOnce(page(Array.from({ length: 100 }, (_, index) => notification(index + 1))))
      .mockResolvedValueOnce(page([], 100));

    await expect(drainNotificationPages({ after: 0, request })).resolves.toEqual({
      nextCursor: 100,
      needsSync: true,
      hasMore: false
    });
    expect(request.mock.calls).toEqual([[0], [100]]);
  });

  it("returns the last validated cursor and asks for sync on an invalid later page", async () => {
    const request = jest.fn()
      .mockResolvedValueOnce(page([notification(1)]))
      .mockResolvedValueOnce({ notifications: "malformed", next_cursor: 2 });

    await expect(drainNotificationPages({ after: 0, request })).resolves.toEqual({
      nextCursor: 1,
      needsSync: true,
      hasMore: false
    });
  });

  it("advances past an unknown kind and still asks for normal sync", async () => {
    await expect(drainNotificationPages({
      after: 4,
      request: async () => page([notification(5, { kind: "future_kind" })])
    })).resolves.toEqual({ nextCursor: 5, needsSync: true, hasMore: false });
  });

  it("keeps hasMore true when a later page is uncertain", async () => {
    const request = jest.fn()
      .mockResolvedValueOnce(page(Array.from({ length: 100 }, (_, index) => notification(index + 1))))
      .mockRejectedValueOnce(new Error("offline"));

    await expect(drainNotificationPages({ after: 0, request })).resolves.toEqual({
      nextCursor: 100,
      needsSync: true,
      hasMore: true
    });
  });

  it("asks for sync after a transport failure without advancing", async () => {
    const request = jest.fn().mockRejectedValue(new Error("offline"));

    await expect(drainNotificationPages({ after: 7, request })).resolves.toEqual({
      nextCursor: 7,
      needsSync: true,
      hasMore: false
    });
  });

  it("asks for sync after an unclassified TypeError without advancing", async () => {
    const request = jest.fn().mockRejectedValue(new TypeError("network failed"));

    await expect(drainNotificationPages({ after: 7, request })).resolves.toEqual({
      nextCursor: 7,
      needsSync: true,
      hasMore: false
    });
  });

  it.each([401, 403])("passes HTTP %i through to the caller", async (status) => {
    const error = Object.assign(new Error("authorization"), { status });
    await expect(drainNotificationPages({ after: 0, request: async () => { throw error; } }))
      .rejects.toBe(error);
  });

  it("passes through a caller-classified auth error without numeric status", async () => {
    class SessionRevokedError extends Error {
      constructor() {
        super("Sign in again");
        this.name = "SessionRevokedError";
      }
    }
    const error = new SessionRevokedError();

    await expect(drainNotificationPages({
      after: 0,
      request: async () => { throw error; },
      isAuthorizationError: (value) => value instanceof Error && value.name === "SessionRevokedError"
    })).rejects.toBe(error);
  });

  it("asks for sync when the bounded page budget ends on a full page", async () => {
    const request = jest.fn().mockResolvedValue(page(Array.from({ length: 100 }, (_, index) => notification(index + 1))));

    await expect(drainNotificationPages({ after: 0, request, maxPages: 1 })).resolves.toEqual({
      nextCursor: 100,
      needsSync: true,
      hasMore: true
    });
    expect(request).toHaveBeenCalledTimes(1);
  });

  it("rejects an unbounded page budget", async () => {
    await expect(drainNotificationPages({ after: 0, request: async () => page([]), maxPages: 11 }))
      .rejects.toThrow(NotificationPollError);
  });
});

describe("createNotificationPollGate", () => {
  it("allows the first start when the clock is zero and enforces the 30-second floor", async () => {
    let time = 0;
    const gate = createNotificationPollGate({ now: () => time, minIntervalMs: 1 });
    const task = jest.fn().mockResolvedValue("first");

    await expect(gate.run(task)).resolves.toBe("first");
    await expect(gate.run(task)).resolves.toBeUndefined();
    expect(task).toHaveBeenCalledTimes(1);

    time = 30_000;
    await expect(gate.run(task)).resolves.toBe("first");
    expect(task).toHaveBeenCalledTimes(2);
  });

  it("coalesces in-flight calls onto the same result", async () => {
    let resolveTask!: (value: string) => void;
    const task = jest.fn(() => new Promise<string>((resolve) => { resolveTask = resolve; }));
    const gate = createNotificationPollGate({ now: () => 0 });
    const first = gate.run(task);
    const second = gate.run(task);

    expect(first).toBe(second);
    await Promise.resolve();
    resolveTask("done");
    await expect(second).resolves.toBe("done");
    expect(task).toHaveBeenCalledTimes(1);
  });
});
