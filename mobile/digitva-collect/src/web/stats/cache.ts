/**
 * In-memory response cache of the Statistics screen, so quick tab switches show data at once instead of reloading.
 * Memory only (no browser storage): a page load or sign-out navigation drops it. Entries belong to one user and access
 * (setStatsScope clears them when either changes). A fresh entry (TTL_MS) answers with no request; a stale one answers
 * at once and refreshes in the background; the same key asked for while a request is out shares that request. Errors
 * are never stored. A stored reply is the server's own, so freshness lines show its time, not the time it was read.
 */
import {
  getAreaProjects, getAreaSummary, getStageCounts, listCases,
  type AreaProject, type AreaQuery, type AreaSummary, type CaseListPage, type CaseListQuery, type StageCountsReply,
} from "../../area/api";
import type { JsonRequester } from "../../workspace/api";

export const TTL_MS = 60_000;
const MAX_ENTRIES = 100;
/** Wait after the visible tab's requests settle before prefetching the other tabs. */
export const PREFETCH_DELAY_MS = 250;

/** One cacheable request: its key (endpoint plus normalised query) and how to fetch it. */
export interface StatsEntry<T> { key: string; fetch: () => Promise<T> }

const entries = new Map<string, { value: unknown; at: number }>();
const inFlight = new Map<string, Promise<unknown>>();
let scope = "";
// Bumped on every clear: a reply requested before it is never stored after it.
let generation = 0;

export function clearStatsCache(): void {
  entries.clear();
  inFlight.clear();
  generation += 1;
}

/** The user and access the entries belong to; a change (another user, role or grant, or sign-out) clears them. */
export function setStatsScope(signature: string): void {
  if (signature === scope) return;
  clearStatsCache();
  scope = signature;
}

/** Endpoint plus the query with empty values dropped and keys sorted, so equal queries share a key. */
function statsKey(endpoint: string, params: Record<string, string | null | undefined>): string {
  return JSON.stringify([endpoint, Object.keys(params).filter((name) => params[name]).sort().map((name) => [name, params[name]])]);
}

export const projectsEntry = (request: JsonRequester): StatsEntry<AreaProject[]> =>
  ({ key: statsKey("projects", {}), fetch: () => getAreaProjects(request) });
export const summaryEntry = (request: JsonRequester, query: AreaQuery): StatsEntry<AreaSummary> =>
  ({ key: statsKey("summary", { project: query.project, unit: query.unit, site: query.site, period: query.period }), fetch: () => getAreaSummary(request, query) });
export const stageCountsEntry = (request: JsonRequester, query: CaseListQuery): StatsEntry<StageCountsReply> =>
  ({ key: statsKey("stage-counts", query), fetch: () => getStageCounts(request, query) });
export const casesEntry = (request: JsonRequester, query: CaseListQuery): StatsEntry<CaseListPage> =>
  ({ key: statsKey("cases", query), fetch: () => listCases(request, query) });

/** The stored value, fresh or stale; undefined when there is none. */
export function peekStats<T>(entry: StatsEntry<T>): T | undefined {
  return entries.get(entry.key)?.value as T | undefined;
}

function load<T>(entry: StatsEntry<T>): Promise<T> {
  const running = inFlight.get(entry.key);
  if (running) return running as Promise<T>;
  const mine = generation;
  // A fetch that throws before returning a promise is a rejection like any other.
  const promise = new Promise<T>((resolve) => resolve(entry.fetch())).then((value) => {
    if (mine === generation) {
      entries.delete(entry.key);
      entries.set(entry.key, { value, at: Date.now() });
      if (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value!);
    }
    return value;
  });
  inFlight.set(entry.key, promise);
  const done = () => {
    if (inFlight.get(entry.key) === promise) inFlight.delete(entry.key);
  };
  promise.then(done, done);
  return promise;
}

/** Fresh: `cached` only. Stale: `cached` and the refresh as `next`. Missing: `next` only. */
export function readStats<T>(entry: StatsEntry<T>): { cached?: T; next?: Promise<T> } {
  const hit = entries.get(entry.key);
  if (hit && Date.now() - hit.at < TTL_MS) return { cached: hit.value as T };
  return { cached: hit?.value as T | undefined, next: load(entry) };
}

/**
 * Hands *onValue* the stored value at once, then the fetched one when it lands. *onError* runs only when nothing was
 * shown: a failed background refresh keeps the stale value on screen.
 */
export function followStats<T>(entry: StatsEntry<T>, onValue: (value: T) => void, onError: (caught: unknown) => void): void {
  const { cached, next } = readStats(entry);
  if (cached !== undefined) onValue(cached);
  next?.then(onValue, (caught) => {
    if (cached === undefined) onError(caught);
  });
}

/**
 * Prefetches *list* one at a time, after the requests already out (the visible tab's) settle and a short pause, so it
 * never delays the visible tab. Fresh entries are skipped; one already out is shared. Returns a cancel: entries not yet
 * started are dropped (one under way finishes and is stored under its own key, never another).
 */
export function prefetchStats(list: StatsEntry<unknown>[]): () => void {
  let cancelled = false;
  const mine = generation;
  const stopped = () => cancelled || mine !== generation;
  void (async () => {
    await Promise.allSettled([...inFlight.values()]);
    await new Promise((resolve) => setTimeout(resolve, PREFETCH_DELAY_MS));
    for (const entry of list) {
      if (stopped()) return;
      const { next } = readStats(entry);
      if (next) await next.catch(() => undefined);
    }
  })();
  return () => {
    cancelled = true;
  };
}
