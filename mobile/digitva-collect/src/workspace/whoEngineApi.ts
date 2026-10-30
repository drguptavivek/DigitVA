/**
 * The WHO client of the offline coding flow: the same WHO calls the DigitVA server makes (app/services/who_icd_api.py,
 * icd11_postcoordination.py, icd11_titles.py), answered by the on-phone engine instead of the WHO container.
 *
 * It returns WHO's JSON as it is; the DigitVA rules that reshape it (dorisTerminology.ts, dorisCertificate.ts,
 * dorisProcessing.ts) are ports of the server's and live beside it. Rules of this layer:
 * - Search always sends the server's options (`q` with a trailing `%`, includePostcoordination, flatResults,
 *   highlightingEnabled, medicalCodingMode, subtreesFilter) and a `limit`, so the engine answers a short list.
 * - Nothing here ever asks for `include=descendant` (the engine refuses it), so no reply is a whole subtree.
 * - A failed engine call never carries the engine's text: it is a WhoUnavailableError with a fixed reason, which the
 *   editor turns into the server's WHO_API_UNAVAILABLE. A WHO 404 is an answer, not a failure, as on the server.
 * - Codeinfo and entity replies (and titles) are cached per client, capped; WHO's data does not change while the
 *   app runs. Failures are never cached. The client lives as long as one offline case screen.
 */
import type { OfflineEngine } from "../offlineEngine";
import { codePointLength, isRecord, or, plainText, type JsonRecord } from "./whoText";

/** The release the engine ships and the server pins (app/services/who_icd_api.py DEFAULT_ICD11_RELEASE). */
export const WHO_RELEASE = "2026-01";
export const WHO_URI_PREFIX = "http://id.who.int/";

/**
 * What each offline coding records about the engine that judged it. The release is the one pinned in
 * scripts/icd11-engine.env, copied here because the JS bundle has no other way to know which engine the APK ships
 * (a jest test fails when the two differ); the DORIS versions are the ones the bundled data files carry
 * (DORIS_v2.1_1.2.0 rules, rule engine 1.1.176).
 */
export const ENGINE_PROVENANCE = {
  icd11_engine: "2026.10.29.1",
  doris_engine: "1.1.176",
  doris_rules: "1.2.0",
  icd_release: WHO_RELEASE,
} as const;

const MAX_EXPRESSION_CHARS = 256; // get_icd11_codeinfo
const CACHE_ENTRIES = 128;
// A stem URI the server fetches through proxy_who_icd_request: a linearization entity (optionally a residual child) or a foundation entity.
const LINEARIZATION_URI = new RegExp(`^${WHO_URI_PREFIX.replace(/\./g, "\\.")}icd/release/11/(?:${WHO_RELEASE}/)?mms/(\\d+)(?:/(unspecified|other))?$`);
const FOUNDATION_URI = new RegExp(`^${WHO_URI_PREFIX.replace(/\./g, "\\.")}icd/entity/(\\d+)$`);

/** WHO (here the engine) could not give a usable answer: the server's WhoIcdApiUnavailable. The reason is a fixed text, never the engine's. */
export class WhoUnavailableError extends Error {
  constructor(reason: string) {
    super(reason);
    this.name = "WhoUnavailableError";
  }
}

/** An entity read: the entity, or WHO's answer that there is none (a 4xx, or a reply that is not an object). */
export type EntityRead = { kind: "ok"; entity: JsonRecord } | { kind: "absent"; status: number };

/** One DORIS or CoDEdit run, as the server's `_run_engine` sees the HTTP answer. */
export type ProcessorOutcome = { kind: "ok"; data: unknown } | { kind: "malformed" } | { kind: "unavailable" };

export interface WhoEngineApi {
  /** `POST mms/search`: WHO's `destinationEntities` and `resultChopped`. */
  search(query: string, options: { limit: number; subtreeUris?: readonly string[] }): Promise<{ entities: unknown[]; chopped: unknown }>;
  /** `get_icd11_codeinfo`: WHO's codeinfo for a stem or expression, null when WHO has no such code. */
  codeinfo(expression: string): Promise<JsonRecord | null>;
  /** A linearization or foundation entity by its URI. */
  entity(uri: string): Promise<EntityRead>;
  /** `_who_title`: WHO's title for one code ("" when WHO has none). */
  title(token: string): Promise<string>;
  /** `post_mortality_processor` for `doris` or `codedit`. */
  runProcessor(name: "doris" | "codedit", certificate: unknown): Promise<ProcessorOutcome>;
}

/** A map that forgets its oldest entry past `max` (insertion order), so a long session cannot grow it without bound. */
function boundedCache<V>(max: number) {
  const entries = new Map<string, V>();
  return {
    has: (key: string) => entries.has(key),
    get: (key: string) => entries.get(key),
    set(key: string, value: V) {
      if (!entries.has(key) && entries.size >= max) entries.delete(entries.keys().next().value as string);
      entries.set(key, value);
    },
  };
}

export function createWhoEngineApi(engine: OfflineEngine): WhoEngineApi {
  const codeinfos = boundedCache<JsonRecord | null>(CACHE_ENTRIES);
  const entities = boundedCache<JsonRecord>(CACHE_ENTRIES);
  const titles = boundedCache<string>(CACHE_ENTRIES);

  async function codeinfo(expression: string): Promise<JsonRecord | null> {
    const text = expression.trim();
    if (!text || codePointLength(text) > MAX_EXPRESSION_CHARS) return null;
    if (codeinfos.has(text)) return codeinfos.get(text) ?? null;
    const result = await engine.codeinfo(text);
    if (!result.ok) {
      if (result.status !== 404) throw new WhoUnavailableError("codeinfo_failed");
      codeinfos.set(text, null);
      return null;
    }
    if (!isRecord(result.data)) throw new WhoUnavailableError("codeinfo_malformed");
    codeinfos.set(text, result.data);
    return result.data;
  }

  async function entity(uri: string): Promise<EntityRead> {
    const cached = entities.get(uri);
    if (cached) return { kind: "ok", entity: cached };
    const foundation = FOUNDATION_URI.exec(uri);
    const linearization = foundation ? null : LINEARIZATION_URI.exec(uri);
    if (!foundation && !linearization) throw new WhoUnavailableError("entity_uri_invalid");
    const result = foundation
      ? await engine.foundationEntity(foundation[1])
      : await engine.entity(linearization![1], linearization![2] ? { residual: linearization![2] } : undefined);
    if (!result.ok) {
      // The server reads a 4xx body as "no entity" and raises for anything else (5xx, no answer at all).
      if (result.status !== undefined && result.status >= 400 && result.status < 500) return { kind: "absent", status: result.status };
      throw new WhoUnavailableError("entity_failed");
    }
    if (!isRecord(result.data)) return { kind: "absent", status: result.status };
    entities.set(uri, result.data);
    return { kind: "ok", entity: result.data };
  }

  async function title(token: string): Promise<string> {
    const cached = titles.get(token);
    if (cached !== undefined) return cached;
    const found = await whoTitle(token);
    titles.set(token, found);
    return found;
  }

  /** icd11_titles._who_title: codeinfo's own title, else the title of the entity its stemId points at. */
  async function whoTitle(token: string): Promise<string> {
    const info = await codeinfo(token);
    if (!info || info.code !== token) return "";
    const own = plainText(or(info.title, info.label));
    if (own) return own;
    const stemUri = info.stemId;
    if (typeof stemUri !== "string" || !stemUri.startsWith(WHO_URI_PREFIX)) return "";
    const read = await entity(stemUri);
    if (read.kind === "ok") return plainText(or(read.entity.title, read.entity.label));
    // 404, or a 200 that is not an entity: no such code. Any other status is not an answer about the code.
    if (read.status === 404 || read.status === 200) return "";
    throw new WhoUnavailableError("entity_failed");
  }

  return {
    async search(query, { limit, subtreeUris }) {
      const result = await engine.search(`${query.trim()}%`, {
        includePostcoordination: true,
        flatResults: true,
        highlightingEnabled: true,
        medicalCodingMode: true,
        ...(subtreeUris?.length ? { subtreesFilter: subtreeUris.join(",") } : {}),
        limit,
      });
      if (!result.ok) throw new WhoUnavailableError("search_failed");
      const raw = result.data;
      if (!isRecord(raw) || !Array.isArray(raw.destinationEntities)) throw new WhoUnavailableError("search_malformed");
      return { entities: raw.destinationEntities, chopped: raw.resultChopped };
    },
    codeinfo,
    entity,
    title,
    async runProcessor(name, certificate) {
      const result = await (name === "doris" ? engine.doris(certificate) : engine.codedit(certificate));
      if (result.ok) return { kind: "ok", data: result.data };
      // Not JSON is the server's malformed_response; a refused or failed run (any status, no answer) is unavailable.
      return result.error === "bad_json" ? { kind: "malformed" } : { kind: "unavailable" };
    },
  };
}
