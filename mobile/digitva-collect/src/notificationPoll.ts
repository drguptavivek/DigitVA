const PAGE_SIZE = 100;
const DEFAULT_MAX_PAGES = 10;
const MIN_POLL_INTERVAL_MS = 30_000;
const MAX_PROJECT_ID_LENGTH = 6;
const MAX_KIND_LENGTH = 32;
const MAX_VA_SID_LENGTH = 64;
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const OFFSET_TIMESTAMP_PATTERN = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/i;

export class NotificationPollError extends Error {
  constructor() {
    super("Invalid notification poll response.");
    this.name = "NotificationPollError";
  }
}

export type NotificationPage = {
  nextCursor: number;
  nonEmpty: boolean;
  hasMore: boolean;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isSafeCursor(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isNullableUuid(value: unknown): boolean {
  return value === null || (typeof value === "string" && UUID_PATTERN.test(value));
}

function isOffsetTimestamp(value: unknown): value is string {
  if (typeof value !== "string") {
    return false;
  }

  const parts = OFFSET_TIMESTAMP_PATTERN.exec(value);
  if (!parts) {
    return false;
  }

  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = parts;
  const date = new Date(0);
  date.setUTCFullYear(Number(year), Number(month) - 1, Number(day));
  date.setUTCHours(Number(hour), Number(minute), Number(second), 0);
  return Number.isFinite(Date.parse(value))
    && date.getUTCFullYear() === Number(year)
    && date.getUTCMonth() === Number(month) - 1
    && date.getUTCDate() === Number(day)
    && date.getUTCHours() === Number(hour)
    && date.getUTCMinutes() === Number(minute)
    && date.getUTCSeconds() === Number(second)
    && Number(hour) <= 23
    && Number(minute) <= 59
    && Number(second) <= 59
    && (offsetHour === undefined || (Number(offsetHour) <= 23 && Number(offsetMinute) <= 59));
}

/**
 * Validate one backend page without retaining its notification rows.
 * Empty pages may rewind after a database restore; nonempty pages must advance
 * exactly to their final row so malformed data cannot skip unvalidated rows.
 */
export function parseNotificationPage(payload: unknown, after: number): NotificationPage {
  if (!isSafeCursor(after) || !isRecord(payload) || !Array.isArray(payload.notifications)
    || !isSafeCursor(payload.next_cursor) || payload.notifications.length > PAGE_SIZE) {
    throw new NotificationPollError();
  }

  let lastId = after;
  for (const value of payload.notifications) {
    if (!isRecord(value)
      || !isSafeCursor(value.id)
      || value.id <= lastId
      || typeof value.kind !== "string"
      || value.kind.trim().length === 0
      || value.kind.length > MAX_KIND_LENGTH
      || typeof value.project_id !== "string"
      || value.project_id.length > MAX_PROJECT_ID_LENGTH
      || !isOffsetTimestamp(value.created_at)
      || !isNullableUuid(value.death_id)
      || !isNullableUuid(value.draft_id)
      || !(value.va_sid === null || (typeof value.va_sid === "string" && value.va_sid.length <= MAX_VA_SID_LENGTH))) {
      throw new NotificationPollError();
    }
    lastId = value.id;
  }

  const nonEmpty = payload.notifications.length > 0;
  if (nonEmpty && payload.next_cursor !== lastId) {
    throw new NotificationPollError();
  }

  return {
    nextCursor: payload.next_cursor,
    nonEmpty,
    hasMore: payload.notifications.length === PAGE_SIZE
  };
}

export type DrainNotificationPagesOptions = {
  after: number;
  request: (after: number) => Promise<unknown>;
  maxPages?: number;
  isAuthorizationError?: (error: unknown) => boolean;
};

export type NotificationDrainResult = {
  nextCursor: number;
  needsSync: boolean;
  hasMore: boolean;
};

function isAuthorizationError(error: unknown): boolean {
  if (!isRecord(error)) {
    return false;
  }

  const response = isRecord(error.response) ? error.response : undefined;
  return error.status === 401 || error.status === 403 || response?.status === 401 || response?.status === 403;
}

/**
 * Drain a bounded sequence of validated pages. Any nonempty page or uncertain
 * response asks the caller to run normal sync; auth errors remain caller-owned.
 */
export async function drainNotificationPages({
  after,
  request,
  maxPages = DEFAULT_MAX_PAGES,
  isAuthorizationError: classifyAuthorizationError
}: DrainNotificationPagesOptions): Promise<NotificationDrainResult> {
  if (!isSafeCursor(after) || !Number.isSafeInteger(maxPages) || maxPages < 1 || maxPages > DEFAULT_MAX_PAGES) {
    throw new NotificationPollError();
  }

  let nextCursor = after;
  let needsSync = false;
  let hasMore = false;

  for (let pageNumber = 0; pageNumber < maxPages; pageNumber += 1) {
    let payload: unknown;
    try {
      payload = await request(nextCursor);
    } catch (error) {
      if (isAuthorizationError(error) || classifyAuthorizationError?.(error)) {
        throw error;
      }
      return { nextCursor, needsSync: true, hasMore };
    }

    let page: NotificationPage;
    try {
      page = parseNotificationPage(payload, nextCursor);
    } catch {
      return { nextCursor, needsSync: true, hasMore };
    }

    nextCursor = page.nextCursor;
    hasMore = page.hasMore;
    needsSync ||= page.nonEmpty;
    if (!hasMore) {
      break;
    }
  }

  return { nextCursor, needsSync, hasMore };
}

export type NotificationPollGateOptions = {
  now?: () => number;
  minIntervalMs?: number;
};

/**
 * Coalesce concurrent polls and enforce the 30-second server floor per caller.
 * Identity changes and cursor persistence belong to the caller.
 */
export function createNotificationPollGate({
  now = Date.now,
  minIntervalMs = MIN_POLL_INTERVAL_MS
}: NotificationPollGateOptions = {}) {
  const interval = Number.isFinite(minIntervalMs)
    ? Math.max(MIN_POLL_INTERVAL_MS, minIntervalMs)
    : MIN_POLL_INTERVAL_MS;
  let lastStartedAt: number | undefined;
  let inFlight: Promise<unknown> | undefined;

  return {
    run<T>(task: () => Promise<T>): Promise<T | undefined> {
      if (inFlight) {
        return inFlight as Promise<T>;
      }

      const startedAt = now();
      if (lastStartedAt !== undefined && startedAt - lastStartedAt < interval) {
        return Promise.resolve(undefined);
      }

      lastStartedAt = startedAt;
      const current = Promise.resolve().then(task);
      inFlight = current;
      const clear = () => {
        if (inFlight === current) {
          inFlight = undefined;
        }
      };
      void current.then(clear, clear);
      return current;
    }
  };
}
