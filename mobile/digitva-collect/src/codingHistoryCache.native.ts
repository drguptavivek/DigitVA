import type { Db } from "./drafts";
import type { CoderHistory, CoderHistoryCase } from "./workspace/contracts";
import type { CachedCodingHistoryPage, CodingHistoryCache, CodingHistoryIdentity } from "./codingHistoryCache";

const MAX_CASES = 500;
const MAX_PAGES = 10;

type StoredCase = Pick<CoderHistoryCase,
  "va_sid" | "va_uniqueid_masked" | "project_id" | "site_id" | "va_submission_date" | "va_coding_date" | "va_code_status" | "recode_until">;

function safePage(page: CoderHistory, projectId: string): { page: CoderHistory; cases: StoredCase[] } {
  if (!Array.isArray(page.history) || !Number.isInteger(page.count) || page.count < 0 ||
      !Number.isInteger(page.limit) || page.limit < 1 || !Number.isInteger(page.offset) || page.offset < 0 ||
      typeof page.has_more !== "boolean") throw new Error("coding_history_cache_invalid_page");
  const cases = page.history.map((item): StoredCase => {
    if (typeof item.va_sid !== "string" || !item.va_sid || typeof item.va_uniqueid_masked !== "string" ||
        item.project_id !== projectId || typeof item.site_id !== "string" || typeof item.va_submission_date !== "string" ||
        typeof item.va_coding_date !== "string" || typeof item.va_code_status !== "string" ||
        (item.recode_until != null && typeof item.recode_until !== "string")) throw new Error("coding_history_cache_invalid_case");
    return {
      va_sid: item.va_sid,
      va_uniqueid_masked: item.va_uniqueid_masked,
      project_id: item.project_id,
      site_id: item.site_id,
      va_submission_date: item.va_submission_date,
      va_coding_date: item.va_coding_date,
      va_code_status: item.va_code_status,
      ...(item.recode_until != null ? { recode_until: item.recode_until } : {}),
    };
  });
  return { page: { ...page, history: cases.map((item) => ({
    ...item, va_form_id: "", va_deceased_age: null, va_deceased_gender: null, recodeable: false,
  })) }, cases };
}

function parsedCases(raw: string, expectedProjectId: string): CoderHistoryCase[] {
  const value: unknown = JSON.parse(raw);
  if (!Array.isArray(value)) throw new Error("coding_history_cache_invalid_page");
  return value.map((item: unknown) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) throw new Error("coding_history_cache_invalid_case");
    const row = item as Record<string, unknown>;
    if (typeof row.va_sid !== "string" || typeof row.va_uniqueid_masked !== "string" ||
        row.project_id !== expectedProjectId || typeof row.site_id !== "string" ||
        typeof row.va_submission_date !== "string" || typeof row.va_coding_date !== "string" ||
        typeof row.va_code_status !== "string" || (row.recode_until != null && typeof row.recode_until !== "string")) {
      throw new Error("coding_history_cache_invalid_case");
    }
    return {
      va_sid: row.va_sid, va_uniqueid_masked: row.va_uniqueid_masked, project_id: row.project_id,
      site_id: row.site_id, va_submission_date: row.va_submission_date, va_coding_date: row.va_coding_date,
      va_code_status: row.va_code_status, recode_until: row.recode_until as string | null | undefined,
      va_form_id: "", va_deceased_age: null, va_deceased_gender: null, recodeable: false,
    };
  });
}

export async function createNativeCodingHistoryCache(
  db: Db,
  identity: CodingHistoryIdentity,
  accessFingerprint?: string,
): Promise<CodingHistoryCache> {
  const currentAccessFingerprint = /^[a-f0-9]{64}$/i.test(accessFingerprint ?? "") ? accessFingerprint! : undefined;
  if (currentAccessFingerprint) {
    const cached = await db.getAllAsync<{ project_id: string; access_fingerprint: string }>(
      "SELECT DISTINCT project_id, access_fingerprint FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ?",
      [identity.mode, identity.serverOrigin, identity.userId],
    );
    for (const row of cached) {
      if (currentAccessFingerprint !== row.access_fingerprint) {
        await db.runAsync(
          "DELETE FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ?",
          [identity.mode, identity.serverOrigin, identity.userId, row.project_id],
        );
      }
    }
  }
  const baseArgs = [identity.mode, identity.serverOrigin, identity.userId] as const;
  const matchesIdentity = (scope: CodingHistoryIdentity) =>
    scope.mode === identity.mode && scope.serverOrigin === identity.serverOrigin && scope.userId === identity.userId;
  const invalidateProject = async (_scope: CodingHistoryIdentity, projectId?: string): Promise<void> => {
    await db.runAsync(
      projectId
        ? "DELETE FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ?"
        : "DELETE FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ?",
      projectId ? [...baseArgs, projectId] : [...baseArgs],
    );
  };
  return {
    async cachedProjects(scope): Promise<string[]> {
      if (!matchesIdentity(scope)) return [];
      const rows = await db.getAllAsync<{ project_id: string }>(
        `SELECT project_id FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND offset = 0
         GROUP BY project_id ORDER BY MAX(fetched_at) DESC LIMIT 10`,
        [...baseArgs],
      );
      return rows.map((row) => row.project_id);
    },
    fingerprintForProject: (_projectId) => currentAccessFingerprint,
    async readPage(scope, projectId, offset): Promise<CachedCodingHistoryPage | null> {
      if (!matchesIdentity(scope)) return null;
      const row = await db.getFirstAsync<{
        access_fingerprint: string; offset: number; page_limit: number; total_count: number;
        has_more: number; fetched_at: string; cases_json: string;
      }>(
        `SELECT access_fingerprint, offset, page_limit, total_count, has_more, fetched_at, cases_json
         FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ? AND offset = ?
         ORDER BY fetched_at DESC LIMIT 1`,
        [...baseArgs, projectId, offset],
      );
      if (!row) return null;
      if (!currentAccessFingerprint || currentAccessFingerprint !== row.access_fingerprint) {
        await invalidateProject(scope, projectId);
        return null;
      }
      try {
        const history = parsedCases(row.cases_json, projectId);
        const hasCachedNextPage = row.has_more === 1 && await db.getFirstAsync<{ present: number }>(
          `SELECT 1 AS present FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ? AND access_fingerprint = ? AND offset = ? LIMIT 1`,
          [...baseArgs, projectId, currentAccessFingerprint, row.offset + row.page_limit],
        );
        const page: CoderHistory = {
          history, count: row.total_count, limit: row.page_limit, offset: row.offset, has_more: Boolean(hasCachedNextPage),
        };
        return { page, fetchedAt: row.fetched_at, accessFingerprint: row.access_fingerprint };
      } catch {
        await db.runAsync(
          "DELETE FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ? AND offset = ?",
          [...baseArgs, projectId, offset],
        );
        return null;
      }
    },
    async writePage(scope, projectId, page, pageFingerprint): Promise<void> {
      if (!matchesIdentity(scope)) return;
      if (!currentAccessFingerprint || pageFingerprint !== currentAccessFingerprint) return;
      const { page: safe, cases } = safePage(page, projectId);
      const now = new Date().toISOString();
      await db.runAsync(
        `DELETE FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ? AND project_id = ? AND access_fingerprint <> ?`,
        [...baseArgs, projectId, currentAccessFingerprint],
      );
      await db.runAsync(
        `INSERT INTO coding_history_cache
          (mode, server_origin, user_id, project_id, access_fingerprint, offset, page_limit, total_count, has_more, fetched_at, case_count, cases_json)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
         ON CONFLICT(mode, server_origin, user_id, project_id, access_fingerprint, offset) DO UPDATE SET
          page_limit = excluded.page_limit, total_count = excluded.total_count, has_more = excluded.has_more,
          fetched_at = excluded.fetched_at, case_count = excluded.case_count, cases_json = excluded.cases_json`,
        [...baseArgs, projectId, currentAccessFingerprint, safe.offset, safe.limit, safe.count, safe.has_more ? 1 : 0, now, cases.length, JSON.stringify(cases)],
      );
      const pages = await db.getAllAsync<{ rowid: number; case_count: number }>(
        `SELECT rowid, case_count FROM coding_history_cache
         WHERE user_id = ? ORDER BY fetched_at DESC, rowid DESC`,
        [identity.userId],
      );
      let retained = 0;
      let retainedPages = 0;
      const stale: number[] = [];
      for (const cached of pages) {
        const size = Math.max(0, Number(cached.case_count) || 0);
        if (retainedPages >= MAX_PAGES || retained + size > MAX_CASES) stale.push(cached.rowid);
        else { retained += size; retainedPages += 1; }
      }
      if (stale.length) {
        await db.runAsync(`DELETE FROM coding_history_cache WHERE rowid IN (${stale.map(() => "?").join(",")})`, stale);
      }
    },
    async invalidateCase(scope, vaSid): Promise<void> {
      if (!matchesIdentity(scope)) return;
      const pages = await db.getAllAsync<{ rowid: number; cases_json: string }>(
        "SELECT rowid, cases_json FROM coding_history_cache WHERE mode = ? AND server_origin = ? AND user_id = ?",
        [...baseArgs],
      );
      const stale: number[] = [];
      for (const page of pages) {
        try {
          const cases: unknown = JSON.parse(page.cases_json);
          if (!Array.isArray(cases) || cases.some((item) => item && typeof item === "object" && (item as Record<string, unknown>).va_sid === vaSid)) {
            stale.push(page.rowid);
          }
        } catch {
          stale.push(page.rowid);
        }
      }
      if (stale.length) await db.runAsync(`DELETE FROM coding_history_cache WHERE rowid IN (${stale.map(() => "?").join(",")})`, stale);
    },
    async invalidateProject(scope, projectId): Promise<void> {
      if (!matchesIdentity(scope)) return;
      await invalidateProject(scope, projectId);
    },
  };
}
