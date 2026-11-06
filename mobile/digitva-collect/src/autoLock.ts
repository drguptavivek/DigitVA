/**
 * Auto-lock timing: lock after 5 minutes without activity, and on return to
 * the foreground after more than 1 minute away. Pure timing; what locking
 * does (save the open draft, close the databases) is the caller's `onLock`.
 * WCAG 2.2.1: `onWarn(true)` fires 30 seconds before the idle lock so the
 * user can stay unlocked (any activity re-arms both timers and calls
 * `onWarn(false)` while a warning is showing).
 */
export const IDLE_LOCK_MS = 5 * 60_000;
export const BACKGROUND_LOCK_MS = 60_000;
export const LOCK_WARNING_MS = 30_000;

export interface AutoLock {
  /** A touch or a draft save: restart the idle timer. */
  activity(): void;
  /** Feed React Native AppState changes ("active", "background", "inactive"). */
  appStateChanged(state: string): void;
  stop(): void;
}

export function createAutoLock(onLock: () => void, now: () => number = Date.now, onWarn?: (warning: boolean) => void): AutoLock {
  let idle: ReturnType<typeof setTimeout> | undefined;
  let warn: ReturnType<typeof setTimeout> | undefined;
  let warning = false;
  let leftAt: number | undefined;
  const setWarning = (next: boolean) => {
    if (warning === next) return;
    warning = next;
    onWarn?.(next);
  };
  const clear = () => {
    if (idle) clearTimeout(idle);
    if (warn) clearTimeout(warn);
  };
  const arm = () => {
    clear();
    setWarning(false);
    if (onWarn) warn = setTimeout(() => setWarning(true), IDLE_LOCK_MS - LOCK_WARNING_MS);
    idle = setTimeout(() => {
      setWarning(false);
      onLock();
    }, IDLE_LOCK_MS);
  };
  arm();
  return {
    activity: arm,
    appStateChanged(state) {
      if (state !== "active") {
        leftAt ??= now();
        return;
      }
      const away = leftAt === undefined ? 0 : now() - leftAt;
      leftAt = undefined;
      if (away > BACKGROUND_LOCK_MS) onLock();
      arm();
    },
    stop() {
      clear();
      setWarning(false);
    }
  };
}
