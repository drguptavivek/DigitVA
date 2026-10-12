/**
 * Reload-survival helpers: which workspace section / queue page the URL names, and the per-section
 * scroll offset kept in sessionStorage. Nothing here is PII: section codes, project ids already
 * offered by the API, page offsets and pixel offsets only. Drafts, answers and notes never come here.
 */

type Param = string | string[] | undefined;
type KeyValueStore = Pick<Storage, "getItem" | "setItem" | "removeItem" | "key" | "length">;

const SCROLL_PREFIX = "digitva.scroll.v1:";
const CODE = /^[A-Za-z0-9_]{1,64}$/;
const PROJECT = /^[A-Za-z0-9_-]{1,32}$/;
const MAX_OFFSET = 1_000_000;
const PAGE_SIZE = 50;

function one(value: Param): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

/** The category code to open: the URL's `section` when the case offers it, otherwise undefined (caller uses its default). */
export function resolveSection(categories: Array<{ code: string }>, section: Param): string | undefined {
  const code = one(section);
  if (!code || !CODE.test(code)) return undefined;
  return categories.some((item) => item.code === code) ? code : undefined;
}

export type QueueView = { projectId?: string; allProjects: boolean; showHistory: boolean; offset: number };

/** Parse queue query params; anything malformed is ignored so a hand-edited URL cannot break the screen. */
export function parseQueueParams(params: { project?: Param; tab?: Param; offset?: Param }): QueueView {
  const project = one(params.project);
  const rawOffset = one(params.offset);
  const offset = rawOffset !== undefined && /^\d{1,7}$/.test(rawOffset) ? Number(rawOffset) : 0;
  return {
    projectId: project && project !== "all" && PROJECT.test(project) ? project : undefined,
    allProjects: project === "all",
    showHistory: one(params.tab) === "history",
    offset: offset <= MAX_OFFSET && offset % PAGE_SIZE === 0 ? offset : 0,
  };
}

/** Query params for the queue state; `all` records an explicit "All projects" so the last-used project is not re-applied. */
export function serializeQueueParams(view: { projectId?: string; showHistory: boolean; offset: number }): Record<string, string | undefined> {
  return {
    project: view.projectId ?? "all",
    tab: view.showHistory ? "history" : undefined,
    offset: view.offset > 0 ? String(view.offset) : undefined,
  };
}

/** True while the URL names a queue (no case): a late queue report after opening a case must not write onto the case URL. */
export function ownsQueueParams(search: string): boolean {
  return !new URLSearchParams(search).has("vaSid");
}

/** True when a case URL still carries queue params and they should be dropped. */
export function hasQueueParams(params: { project?: Param; tab?: Param; offset?: Param }): boolean {
  return params.project !== undefined || params.tab !== undefined || params.offset !== undefined;
}

/** sessionStorage on the web, otherwise undefined; access can throw in private or locked-down browsers. */
export function browserSessionStore(): KeyValueStore | undefined {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : undefined;
  } catch {
    return undefined;
  }
}

const scrollKey = (mode: string, vaSid: string, section: string) => `${SCROLL_PREFIX}${mode}:${vaSid}:${section}`;

export function readScroll(store: KeyValueStore | undefined, mode: string, vaSid: string, section: string): number {
  try {
    const value = Number(store?.getItem(scrollKey(mode, vaSid, section)));
    return Number.isFinite(value) && value > 0 ? Math.round(value) : 0;
  } catch {
    return 0;
  }
}

export function saveScroll(store: KeyValueStore | undefined, mode: string, vaSid: string, section: string, offset: number): void {
  try {
    store?.setItem(scrollKey(mode, vaSid, section), String(Math.max(0, Math.round(offset))));
  } catch {
    // Storage unavailable or full: scroll restore is a convenience only.
  }
}

function removeScroll(store: KeyValueStore | undefined, prefix: string): void {
  try {
    if (!store) return;
    const stale: string[] = [];
    for (let index = 0; index < store.length; index += 1) {
      const key = store.key(index);
      if (key?.startsWith(prefix)) stale.push(key);
    }
    stale.forEach((key) => store.removeItem(key));
  } catch {
    // Nothing to clear.
  }
}

/** Drop every section's offset for a case when the user leaves it. */
export function clearScroll(store: KeyValueStore | undefined, mode: string, vaSid: string): void {
  removeScroll(store, `${SCROLL_PREFIX}${mode}:${vaSid}:`);
}

/** Drop every pinned offset of every case: the pinned offsets are per case and must not outlive the session. */
export function clearAllScroll(store: KeyValueStore | undefined): void {
  removeScroll(store, SCROLL_PREFIX);
}

/** Offset worth restoring once the scroller is `contentHeight` tall inside a `viewport`-tall box. */
export function canRestoreScroll(target: number, contentHeight: number, viewport: number): boolean {
  return target > 0 && contentHeight - viewport >= target;
}
