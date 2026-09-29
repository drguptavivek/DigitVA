/**
 * Auto-lock timing: lock after 5 minutes without activity, and on return to
 * the foreground after more than 1 minute away. Pure timing; what locking
 * does (save the open draft, close the databases) is the caller's `onLock`.
 */
export const IDLE_LOCK_MS = 5 * 60_000;
export const BACKGROUND_LOCK_MS = 60_000;

export interface AutoLock {
  /** A touch or a draft save: restart the idle timer. */
  activity(): void;
  /** Feed React Native AppState changes ("active", "background", "inactive"). */
  appStateChanged(state: string): void;
  stop(): void;
}

export function createAutoLock(onLock: () => void, now: () => number = Date.now): AutoLock {
  let idle: ReturnType<typeof setTimeout> | undefined;
  let leftAt: number | undefined;
  const arm = () => {
    if (idle) clearTimeout(idle);
    idle = setTimeout(onLock, IDLE_LOCK_MS);
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
      if (idle) clearTimeout(idle);
    }
  };
}
