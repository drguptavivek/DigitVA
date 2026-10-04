import type { CaseActionAck, CaseRow, ClientBootstrap } from "../client/api";

/**
 * A list row is the only web-safe case detail available to the Expo client.
 * Keep it in memory, scoped to the exact authenticated bootstrap object. This
 * avoids putting names, phones or addresses in URLs or browser storage.
 */
const previews = new WeakMap<object, Map<string, CaseRow>>();

function mapFor(bootstrap: ClientBootstrap): Map<string, CaseRow> {
  let map = previews.get(bootstrap);
  if (!map) {
    map = new Map<string, CaseRow>();
    previews.set(bootstrap, map);
  }
  return map;
}

export function rememberCasePreviews(bootstrap: ClientBootstrap, rows: CaseRow[]): void {
  const map = mapFor(bootstrap);
  for (const row of rows) map.set(row.death_id, row);
}

export function getCasePreview(bootstrap: ClientBootstrap, deathId: string): CaseRow | undefined {
  return mapFor(bootstrap).get(deathId);
}

export function updateCasePreview(bootstrap: ClientBootstrap, deathId: string, ack: CaseActionAck): CaseRow | undefined {
  const map = mapFor(bootstrap);
  const current = map.get(deathId);
  if (!current) return undefined;
  const next = {
    ...current,
    state: ack.state ?? ack.status,
    status: ack.state ?? ack.status,
    next_visit_at: ack.next_visit_at ?? null,
    last_contact_at: ack.last_contact_at ?? current.last_contact_at ?? null
  };
  map.set(deathId, next);
  return next;
}
