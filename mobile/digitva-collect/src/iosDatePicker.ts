/**
 * The iOS side of platformServices.pickDate (src/platform.ts). iOS has no imperative date dialog like
 * DateTimePickerAndroid.open, so a request is parked here and IosDatePickerHost (mounted once by the native shell)
 * shows it in a modal. Done resolves the request with the picked day as ISO; Cancel or dismissal resolves it with
 * undefined. A new request while one is open resolves the open one with undefined first, so no promise is left hanging.
 */

export interface DateRequest {
  id: number;
  /** The day the picker opens on (local midnight). */
  initial: Date;
}

type Listener = (request: DateRequest | undefined) => void;

let open: (DateRequest & { resolve: (value: string | undefined) => void }) | undefined;
let nextId = 1;
const listeners = new Set<Listener>();

function publish(): void {
  const request = open ? { id: open.id, initial: open.initial } : undefined;
  for (const listener of listeners) listener(request);
}

export function isoFromDate(value: Date): string {
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${value.getFullYear()}-${month}-${day}`;
}

export function dateFromIso(value: string | undefined): Date {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? "");
  if (!match) return new Date();
  return new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

/** Ask for a date; the host shows the picker. Resolves with "YYYY-MM-DD" on Done, undefined otherwise. */
export function requestIosDate(currentValue: string | undefined): Promise<string | undefined> {
  open?.resolve(undefined);
  return new Promise((resolve) => {
    open = { id: nextId++, initial: dateFromIso(currentValue), resolve };
    publish();
  });
}

/** Close request `id`: a Date picks it, undefined cancels. A stale id (already superseded) is ignored. */
export function finishIosDate(id: number, picked: Date | undefined): void {
  if (!open || open.id !== id) return;
  const { resolve } = open;
  open = undefined;
  publish();
  resolve(picked ? isoFromDate(picked) : undefined);
}

/** The host's subscription; it is told the open request at once and on every change. */
export function subscribeIosDate(listener: Listener): () => void {
  listeners.add(listener);
  listener(open ? { id: open.id, initial: open.initial } : undefined);
  return () => {
    listeners.delete(listener);
  };
}
