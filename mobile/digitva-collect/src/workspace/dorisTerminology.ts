/**
 * Terms search and code information for the offline picker: ports of the server's
 * - `search_terms`, `valid_subtree_uris`, `postcoordination_availability`, `search_context_from_entity`
 *   (app/services/icd11_postcoordination.py), and
 * - `selection_refusal` (the same file), which the selection-check routes apply to that item,
 * - `_codeinfo_item` (app/routes/api/doris_clinical.py), which the codeinfo and selection-check routes share,
 * over the WHO client (whoEngineApi.ts). They build the reply bodies the routes send, field for field.
 */
import type { DorisCodeInfoItem, DorisTerm } from "./contracts";
import { expectedExpressionUri } from "./dorisCertificate";
import { WHO_RELEASE, WHO_URI_PREFIX, WhoUnavailableError, type WhoEngineApi } from "./whoEngineApi";
import { isRecord, or, plain, plainText, truthy, type JsonRecord } from "./whoText";

const MAX_SUBTREE_URIS = 40;
// The engine is always asked for the server's maximum (20): the caller's smaller limit then cuts the same list the
// server cuts, and `truncated` agrees (more entities than items).
const ENGINE_LIMIT = 20;
const SUBTREE_URI = /^http:\/\/id\.who\.int\/icd\/\S+$/;

/** The optional WHO subtree scope of a search: absent, or 1 to 40 WHO URIs of at most 200 characters without whitespace. */
export function validSubtreeUris(value: unknown): boolean {
  if (value === undefined || value === null) return true;
  return Array.isArray(value) && value.length >= 1 && value.length <= MAX_SUBTREE_URIS
    && value.every((uri) => typeof uri === "string" && uri.length <= 200 && SUBTREE_URI.test(uri));
}

/** WHO's search flag as it is (0, 1 or 2), and whether postcoordination is available at all. Never guessed from isLeaf or code syntax. */
export function postcoordinationAvailability(value: unknown): { available: boolean; availability: 0 | 1 | 2 | null } {
  const flag = value === 0 || value === 1 || value === 2 ? value : null;
  return { available: Boolean(flag), availability: flag };
}

/** The search badges, derived from a stem entity when a coder enters a code directly. */
export function searchContextFromEntity(entity: JsonRecord): Pick<DorisTerm, "postcoordination" | "postcoordination_availability" | "related_maternal" | "related_perinatal" | "has_coding_note"> {
  const scales = or(entity.postcoordinationScale, []);
  if (!Array.isArray(scales)) throw new WhoUnavailableError("scale_malformed");
  const required = scales.some((scale) => isRecord(scale) && (scale.requiredPostcoordination === true || scale.requiredPostcoordination === "true"));
  return {
    postcoordination: scales.length > 0,
    postcoordination_availability: required ? 2 : scales.length > 0 ? 1 : 0,
    related_maternal: truthy(entity.relatedEntitiesInMaternalChapter),
    related_perinatal: truthy(entity.relatedEntitiesInPerinatalChapter),
    has_coding_note: truthy(entity.codingNote),
  };
}

/** Bounded WHO MMS term search: the items of the terms route (at most `limit`, WHO's order) and whether the list was cut. */
export async function searchTerms(
  who: WhoEngineApi,
  query: string,
  { limit, subtreeUris }: { limit: number; subtreeUris?: readonly string[] },
): Promise<{ items: DorisTerm[]; truncated: boolean }> {
  const { entities, chopped } = await who.search(query, { limit: ENGINE_LIMIT, subtreeUris });
  const items: DorisTerm[] = [];
  for (const entity of entities) {
    if (!isRecord(entity)) continue;
    const code = or(entity.theCode, entity.code);
    const uri = or(or(entity.id, entity.uri), entity["@id"]);
    const title = plain(or(entity.title, entity.titleWithoutCodes), 2000);
    if (![code, uri, title].every((value) => typeof value === "string" && value !== "")) continue;
    let matching: unknown = or(entity.matchingPVs, entity.matchingText);
    // WHO's matchingPVs are objects, which the server's join drops: it then shows the title.
    if (Array.isArray(matching)) matching = matching.filter((item): item is string => typeof item === "string").join(" ");
    const { available, availability } = postcoordinationAvailability(entity.postcoordinationAvailability);
    items.push({
      code: code as string,
      title,
      uri: uri as string,
      release: WHO_RELEASE,
      matching_text: plain(matching, 2000) || title,
      postcoordination: available,
      postcoordination_availability: availability,
      related_maternal: entity.hasMaternalChapterLink === true,
      related_perinatal: entity.hasPerinatalChapterLink === true,
      has_coding_note: entity.hasCodingNote === true,
      extension: typeof entity.chapter === "string" ? entity.chapter === "X" : (code as string).startsWith("X"),
      // Absent isLeaf leaves `leaf` out: the picker reads that as unknown.
      ...(typeof entity.isLeaf === "boolean" ? { leaf: entity.isLeaf } : {}),
    });
    if (items.length === limit) break;
  }
  return { items, truncated: truthy(chopped) || entities.length > items.length };
}

/**
 * The item of the codeinfo and selection-check routes for one code or expression, or null when WHO does not know it.
 * The title is codeinfo's own, else the stem entity's; the badges (postcoordination, availability, maternal, perinatal,
 * coding note) come from that entity and only for a single stem, as on the server. Throws WhoUnavailableError.
 */
export async function codeinfoItem(who: WhoEngineApi, code: string): Promise<DorisCodeInfoItem | null> {
  const info = await who.codeinfo(code);
  if (!info || info.code !== code) return null;
  const uri = await expectedExpressionUri(who, code);
  if (!uri) return null;
  let title = plainText(or(info.title, info.label));
  const stemUri = info.stemId;
  if (typeof stemUri !== "string" || !stemUri.startsWith(WHO_URI_PREFIX)) return null;
  const read = await who.entity(stemUri);
  if (read.kind !== "ok") return null;
  if (!title) title = plainText(or(read.entity.title, read.entity.label));
  if (!title) return null;
  // The first stem only: selectionRefusal checks any further "/" stems.
  const item: DorisCodeInfoItem = { code, title, uri, release: WHO_RELEASE, postcoordination: false, leaf: !truthy(read.entity.child), extension: code.startsWith("X") };
  return code.includes("&") || code.includes("/") ? item : { ...item, ...searchContextFromEntity(read.entity) };
}

/**
 * Why a certificate cannot take a codeinfo item, or null (`selection_refusal`): every stem of the expression (the
 * first token, and the first token after each "/") must not be an extension code and must be a leaf. The first stem's
 * answer is on the item; each further "/" stem costs one codeinfo and one entity read (`_stem`). Throws
 * WhoUnavailableError when WHO cannot say, as the server's 503.
 */
export async function selectionRefusal(who: WhoEngineApi, item: DorisCodeInfoItem): Promise<string | null> {
  const parts = item.code.split("/");
  for (const [index, part] of parts.entries()) {
    const stem = part.split("&", 1)[0];
    if (stem.startsWith("X")) return `${stem} is an extension code. It cannot be used alone: add it to a stem through + Build.`;
    const leaf = index === 0 ? item.leaf === true : await stemIsLeaf(who, stem);
    if (!leaf) return `${stem} is a category, not a final code. Choose a more specific code under it.`;
  }
  return null;
}

/** `_stem(code)[1]` has no `child`: codeinfo, then the stem entity, which must carry the same code. */
async function stemIsLeaf(who: WhoEngineApi, code: string): Promise<boolean> {
  const info = await who.codeinfo(code);
  if (!info || info.code !== code || typeof info.stemId !== "string") throw new WhoUnavailableError("stem_not_found");
  const read = await who.entity(info.stemId);
  if (read.kind !== "ok" || read.entity.code !== code) throw new WhoUnavailableError("stem_unusable");
  return !truthy(read.entity.child);
}
