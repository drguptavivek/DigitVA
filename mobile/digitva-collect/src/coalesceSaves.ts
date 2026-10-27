/**
 * Serialise writes and keep only the newest queued value (digitva-wh4w). Autosave fires on every answer change;
 * on a slow phone each encrypted write outlasts several keystrokes, so queued older snapshots are skipped.
 * Every caller's promise settles when a write that included its value (or a newer one) finishes; nothing waits
 * on a timer, so a flush that awaits the promise still sees the data on disk.
 */
export function coalesceLatest<T>(write: (value: T) => Promise<void>): (value: T) => Promise<void> {
  type Waiter = { resolve: () => void; reject: (error: unknown) => void };
  let running = false;
  let queued: { value: T; waiters: Waiter[] } | undefined;

  async function run(value: T, waiters: Waiter[]): Promise<void> {
    running = true;
    try {
      await write(value);
      waiters.forEach((waiter) => waiter.resolve());
    } catch (error) {
      waiters.forEach((waiter) => waiter.reject(error));
    }
    running = false;
    const next = queued;
    queued = undefined;
    if (next) void run(next.value, next.waiters);
  }

  return (value) =>
    new Promise<void>((resolve, reject) => {
      const waiter = { resolve, reject };
      if (!running) {
        void run(value, [waiter]);
        return;
      }
      queued = { value, waiters: [...(queued?.waiters ?? []), waiter] };
      queued.value = value;
    });
}
