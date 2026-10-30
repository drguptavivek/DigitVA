/**
 * The five ICD-11 picker guidance routes of the offline coding flow: postcoordination (+ Build), postcoordination-options
 * (More choices), hierarchy, related (maternal / perinatal) and details. A port of app/services/icd11_postcoordination.py
 * (`postcoordination`, `_stem`, `_axes`, `_option`, `postcoordination_options`, `hierarchy`, `related_terms`,
 * `code_details`, `_resource`, `_check_budget`, `guidance_request`) and of the body checks of `_guidance_request` in
 * app/routes/api/doris_clinical.py, over the WHO client (whoEngineApi.ts). The replies are the server's, field for field.
 *
 * Bounds, as the server's: 12 axes, 12 options per axis, 12 ancestors, siblings, children and related terms, 20
 * inclusions, 12 exclusions; one request may make 48 WHO reads (GUIDANCE_LIMIT, counted per read the port asks for,
 * whether or not the client's cache answers it) within 10 seconds, and at most two requests run at once (GUIDANCE_BUSY).
 * Children are walked through the entity's own `child` list: nothing here asks the engine for `include=descendant`.
 *
 * Refusals are PostcoordinationError (the server's code, message and status); an engine failure is the WHO client's
 * WhoUnavailableError, which the editor turns into the guidance 503. Input shapes are the server's: any value may reach
 * these functions, so each checks its own type.
 */
import { assertNoPiiInText } from "./piiBoundary";
import { WHO_RELEASE, WHO_URI_PREFIX, WhoUnavailableError, type WhoEngineApi } from "./whoEngineApi";
import { isRecord, or, plain, type JsonRecord } from "./whoText";

export type GuidanceEndpoint = "postcoordination" | "postcoordination-options" | "hierarchy" | "related" | "details";

/** The exact JSON keys (besides schema_version) each route accepts: `_guidance_request(..., fields)` in doris_clinical.py. */
const FIELDS: Record<GuidanceEndpoint, readonly string[]> = {
  postcoordination: ["code"],
  "postcoordination-options": ["stem_code", "axis_id", "parent_uri"],
  hierarchy: ["code"],
  related: ["code", "chapter"],
  details: ["code"],
};

export const GUIDANCE_ENDPOINTS = Object.keys(FIELDS) as GuidanceEndpoint[];

const MAX_AXES = 12;
const MAX_OPTIONS = 12;
const MAX_PATH = 12;
const MAX_TERMS = 12;
const MAX_INCLUSIONS = 20;
const MAX_CALLS = 48;
const GUIDANCE_MS = 10_000;
const CAPACITY = 2;
const MAX_URI_CHARS = 400;
const CODE = /^[A-Z0-9][A-Z0-9./&+-]{0,127}$/;
const AXIS_ID = /^[A-Za-z][A-Za-z0-9]{0,63}$/;
const RELEASE_PATH = `icd/release/11/${WHO_RELEASE}/mms/`;
const ENTITY_PATH = "icd/entity/";
// scheme (any case, as urlsplit lowercases it), the exact host, then the path: no query, no fragment.
const WHO_URI = /^[hH][tT][tT][pP]:\/\/id\.who\.int\/+([^?#]*)$/;
const ENTITY_ID = /^\d+(?:\/(?:unspecified|other))?$/;
const MULTIPLE_VALUES = ["AllowAlways", "NotAllowed", "AllowedExceptFromSameBlock"];
/** WHO MMS chapter X ("Extension Codes"), foundation entity 979408586: "Other postcoordination?" searches this subtree. */
export const X_CHAPTER_URI = `${WHO_URI_PREFIX}icd/release/11/${WHO_RELEASE}/mms/979408586`;
const ROOT_URI = `${WHO_URI_PREFIX}icd/release/11/${WHO_RELEASE}/mms`;

/** The server's PostcoordinationError: a refusal with its code, message and HTTP status (422 unless said). */
export class PostcoordinationError extends Error {
  constructor(readonly code: string, message: string, readonly status: number) {
    super(message);
    this.name = "PostcoordinationError";
  }
}

export interface GuidanceOption {
  code: string;
  title: string;
  uri: string;
  has_children: boolean;
  block_uri?: string;
}

/** The reply of any guidance route: JSON the picker's parsers (workspace/doris/guidance.ts) read. */
export type GuidanceReply = JsonRecord;

const unavailable = (reason: string) => new WhoUnavailableError(reason);
const refuse = (code: string, message: string, status = 422) => new PostcoordinationError(code, message, status);
const isTrue = (value: unknown) => value === true || value === "true";
/** `entity.get(name) or []` as a list, or null when WHO sent something else. */
const listOrNull = (value: unknown): unknown[] | null => {
  const found = or(value, []);
  return Array.isArray(found) ? found : null;
};

/** One request's reads: the server's `_check_budget`, `_resource`, `_entity` and the codeinfo calls that precede a check. */
interface Reader {
  codeinfo(code: string): Promise<JsonRecord | null>;
  entity(uri: unknown, foundation?: boolean): Promise<JsonRecord>;
}

/** `_resource`: the path of a release-pinned MMS entity URI (or a foundation URI), refusing everything else. */
function resource(uri: unknown, foundation = false): string {
  const invalid = () => refuse("INVALID_URI", "Invalid WHO entity URI.");
  if (typeof uri !== "string" || [...uri].length > MAX_URI_CHARS) throw invalid();
  const path = WHO_URI.exec(uri)?.[1];
  const prefix = foundation ? ENTITY_PATH : RELEASE_PATH;
  if (path === undefined || !path.startsWith(prefix) || !ENTITY_ID.test(path.slice(prefix.length))) throw invalid();
  return path;
}

function reader(who: WhoEngineApi, now: () => number): Reader {
  const deadline = now() + GUIDANCE_MS;
  let calls = 0;
  const tick = () => {
    calls += 1;
    if (calls > MAX_CALLS || now() > deadline) throw refuse("GUIDANCE_LIMIT", "WHO guidance exceeded its request limit.", 503);
  };
  return {
    async codeinfo(code) {
      tick();
      return who.codeinfo(code);
    },
    async entity(uri, foundation = false) {
      tick();
      const read = await who.entity(`${WHO_URI_PREFIX}${resource(uri, foundation)}`);
      if (read.kind === "ok") return read.entity;
      if (read.status === 404) throw refuse("CODE_NOT_FOUND", "WHO entity was not found.");
      throw unavailable("entity_unusable");
    },
  };
}

/** `_stem`: the selected stem (code, title, URI) and its entity. */
async function stem(read: Reader, code: unknown): Promise<[GuidanceOption, JsonRecord]> {
  if (typeof code !== "string" || !CODE.test(code)) throw refuse("INVALID_INPUT", "Select one valid ICD-11 stem code.");
  const info = await read.codeinfo(code);
  if (!info || info.code !== code) throw refuse("CODE_NOT_FOUND", "ICD-11 stem code was not found.");
  const uri = info.stemId;
  const entity = await read.entity(uri);
  if (entity.code !== code) throw refuse("CODE_NOT_FOUND", "ICD-11 stem metadata did not match.");
  return [{ code, title: plain(entity.title), uri: uri as string } as GuidanceOption, entity];
}

/** `_stem_code`: the stem an expression (`&`, `/`) is built on, else the code itself; undefined when WHO has no stem for it. */
async function stemCode(read: Reader, code: unknown): Promise<unknown> {
  if (typeof code !== "string" || !(code.includes("&") || code.includes("/"))) return code;
  if (!CODE.test(code)) throw refuse("INVALID_INPUT", "Select a valid ICD-11 expression.");
  const info = await read.codeinfo(code);
  return info?.stemCode;
}

/** `_option`: one coded entity as a picker option, or null for an uncoded leaf when `skipUncodedLeaf`. */
async function option(read: Reader, uri: unknown, blockUri?: string, skipUncodedLeaf = false): Promise<GuidanceOption | null> {
  const entity = await read.entity(uri);
  const children = listOrNull(entity.child) ?? [];
  const { code } = entity;
  const title = plain(entity.title);
  if (code === "" && children.length === 0 && title && skipUncodedLeaf) return null;
  if (typeof code !== "string" || !title || (!code && children.length === 0)) throw unavailable("option_incomplete");
  return { code, title, uri: uri as string, has_children: children.length > 0, ...(blockUri === undefined ? {} : { block_uri: blockUri }) };
}

/** `_axes`: the stem's postcoordination axes, in WHO's order, each with its root options. */
async function axes(read: Reader, entity: JsonRecord): Promise<JsonRecord[]> {
  const raw = listOrNull(entity.postcoordinationScale);
  if (!raw) throw unavailable("scale_malformed");
  if (raw.length > MAX_AXES) throw refuse("GUIDANCE_LIMIT", "WHO returned too many postcoordination axes.", 503);
  const result: JsonRecord[] = [];
  for (const scale of raw) {
    if (!isRecord(scale)) throw unavailable("scale_malformed");
    const { axisName, scaleEntity: roots, requiredPostcoordination: required, allowMultipleValues: multiple } = scale;
    if (
      typeof axisName !== "string" || !Array.isArray(roots)
      || !(typeof required === "boolean" || required === "true" || required === "false")
      || !MULTIPLE_VALUES.includes(multiple as string)
    ) {
      throw unavailable("scale_incomplete");
    }
    const axisId = axisName.slice(axisName.lastIndexOf("/") + 1);
    if (!AXIS_ID.test(axisId)) throw unavailable("axis_invalid");
    const spaced = axisId.replace(/([a-z])(?=[A-Z])/g, "$1 ");
    const label = spaced.charAt(0).toUpperCase() + spaced.slice(1).toLowerCase();
    // A root can be an uncoded leaf (a "window" entity such as FB80.B's "Neoplasms of the musculoskeletal system"): nothing to pick.
    const options: GuidanceOption[] = [];
    for (const uri of roots.slice(0, MAX_OPTIONS)) {
      const found = await option(read, uri, uri as string, true);
      if (found) options.push(found);
    }
    result.push({
      id: axisId,
      label,
      required: isTrue(required),
      instruction: isTrue(required) ? (axisId === "hasCausingCondition" ? "code also" : "use additional code") : "use additional code, if desired",
      allow_multiple: multiple !== "NotAllowed",
      allow_multiple_values: multiple,
      options,
      subtree_uris: roots.slice(0, MAX_OPTIONS),
      truncated: roots.length > MAX_OPTIONS,
    });
  }
  return result;
}

async function postcoordination(read: Reader, code: unknown): Promise<GuidanceReply> {
  const [selected, entity] = await stem(read, code);
  const built = await axes(read, entity);
  return {
    schema_version: 1,
    release: WHO_RELEASE,
    stem: selected,
    axes: built,
    other_postcoordination: entity.classKind === "category" && selected.code && !selected.code.startsWith("X") ? { subtree_uris: [X_CHAPTER_URI] } : null,
    truncated: false,
  };
}

async function postcoordinationOptions(read: Reader, stemCodeValue: unknown, axisId: unknown, parentUri: unknown): Promise<GuidanceReply> {
  const [selected, entity] = await stem(read, stemCodeValue);
  const scales = listOrNull(entity.postcoordinationScale);
  if (!scales) throw unavailable("scale_malformed");
  const scale = scales.slice(0, MAX_AXES).find((item) => (
    isRecord(item) && typeof item.axisName === "string" && item.axisName.slice(item.axisName.lastIndexOf("/") + 1) === axisId
  )) as JsonRecord | undefined;
  if (!scale) throw refuse("INVALID_AXIS", "This axis is not available for the stem.");
  const roots = listOrNull(scale.scaleEntity);
  if (!roots) throw unavailable("axis_roots_malformed");
  resource(parentUri);
  // Walk up from the chosen parent to the axis root it belongs to (WHO's "block"); a parent outside the axis is refused.
  let current = parentUri;
  let inside = false;
  for (let step = 0; step < MAX_PATH; step += 1) {
    if (roots.includes(current)) {
      inside = true;
      break;
    }
    const parents = listOrNull((await read.entity(current)).parent);
    if (!parents || parents.length === 0) throw refuse("INVALID_PARENT", "Parent is outside the selected axis.");
    current = parents[0];
    resource(current);
  }
  if (!inside) throw refuse("INVALID_PARENT", "Parent is outside the selected axis.");
  const children = listOrNull((await read.entity(parentUri)).child);
  if (!children) throw unavailable("option_children_malformed");
  const items: GuidanceOption[] = [];
  for (const uri of children.slice(0, MAX_OPTIONS)) {
    const found = await option(read, uri, current as string, true);
    if (found) items.push(found);
  }
  return {
    schema_version: 1,
    release: WHO_RELEASE,
    stem: selected,
    axis_id: axisId,
    parent_uri: parentUri,
    items,
    truncated: children.length > MAX_OPTIONS,
  };
}

/** The `{code, title, uri}` of a related-chapter entity, as the hierarchy lists it. */
async function relatedOf(read: Reader, uris: unknown[]): Promise<JsonRecord[]> {
  const found: JsonRecord[] = [];
  for (const uri of uris.slice(0, MAX_OPTIONS)) {
    const related = await read.entity(uri, true);
    found.push({ code: or(related.code, ""), title: plain(related.title), uri });
  }
  return found;
}

const MATERNAL = "relatedEntitiesInMaternalChapter";
const PERINATAL = "relatedEntitiesInPerinatalChapter";
/** `len(entity.get(name) or [])` for the one case WHO sends: a list. */
const sizeOf = (value: unknown) => (Array.isArray(value) ? value.length : 0);

async function hierarchy(read: Reader, code: unknown): Promise<GuidanceReply> {
  let expression: JsonRecord | null = null;
  let stemOf = code;
  if (typeof code === "string" && (code.includes("&") || code.includes("/"))) {
    if (!CODE.test(code)) throw refuse("INVALID_INPUT", "Select a valid ICD-11 expression.");
    const info = await read.codeinfo(code);
    if (!info || info.code !== code) throw refuse("CODE_NOT_FOUND", "ICD-11 expression was not found.");
    stemOf = info.stemCode;
    if (typeof stemOf !== "string" || !stemOf) throw unavailable("expression_stem_missing");
    expression = { code, stem_code: stemOf };
  }
  const [selected, entity] = await stem(read, stemOf);
  const ancestors: JsonRecord[] = [];
  let current = entity;
  const seen = new Set<unknown>([selected.uri]);
  for (let step = 0; step < MAX_PATH; step += 1) {
    const parents = or(current.parent, []);
    if (!Array.isArray(parents) || parents.length === 0) break;
    const parentUri = parents[0];
    if (parentUri === ROOT_URI || seen.has(parentUri)) break;
    seen.add(parentUri);
    current = await read.entity(parentUri);
    ancestors.push({ code: or(current.code, ""), title: plain(current.title), uri: parentUri });
  }
  ancestors.reverse();
  const parentChildren = ancestors.length > 0 ? or((await read.entity(ancestors[ancestors.length - 1].uri)).child, []) : [];
  const children = or(entity.child, []);
  if (!Array.isArray(parentChildren) || !Array.isArray(children)) throw unavailable("hierarchy_malformed");
  const siblings = parentChildren.filter((uri) => uri !== selected.uri);
  const terms = listOrNull(entity.indexTerm) ?? [];
  const maternal = listOrNull(entity[MATERNAL]) ?? [];
  const perinatal = listOrNull(entity[PERINATAL]) ?? [];
  // The server reads the related chapters before it builds the sibling and child options; the order decides which read hits the budget.
  const relatedMaternal = await relatedOf(read, maternal);
  const relatedPerinatal = await relatedOf(read, perinatal);
  const siblingOptions: unknown[] = [];
  for (const uri of siblings.slice(0, MAX_OPTIONS)) siblingOptions.push(await option(read, uri));
  const childOptions: unknown[] = [];
  for (const uri of children.slice(0, MAX_OPTIONS)) childOptions.push(await option(read, uri));
  return {
    schema_version: 1,
    release: WHO_RELEASE,
    selected,
    selected_expression: expression,
    ancestors,
    siblings: siblingOptions,
    children: childOptions,
    matching_terms: terms.slice(0, MAX_TERMS).flatMap((term) => (isRecord(term) && plain(term.label) ? [plain(term.label)] : [])),
    related_maternal: relatedMaternal,
    related_perinatal: relatedPerinatal,
    truncated: ancestors.length === MAX_PATH
      || siblings.length > MAX_OPTIONS
      || children.length > MAX_OPTIONS
      || terms.length > MAX_TERMS
      || sizeOf(entity[MATERNAL]) > MAX_OPTIONS
      || sizeOf(entity[PERINATAL]) > MAX_OPTIONS,
  };
}

async function relatedTerms(read: Reader, code: unknown, chapter: unknown): Promise<GuidanceReply> {
  const source = chapter === "maternal" ? MATERNAL : chapter === "perinatal" ? PERINATAL : null;
  if (!source) throw refuse("INVALID_INPUT", "Choose a valid related chapter.");
  const [selected, entity] = await stem(read, await stemCode(read, code));
  const relatedUris = listOrNull(entity[source]);
  if (!relatedUris) throw unavailable("related_malformed");
  const terms: JsonRecord[] = [];
  let composite: JsonRecord | null = null;
  let truncated = relatedUris.length > MAX_OPTIONS;
  for (const foundationUri of relatedUris.slice(0, MAX_OPTIONS)) {
    const entityId = resource(foundationUri, true).split("/").pop();
    let related: JsonRecord;
    try {
      related = await read.entity(`${WHO_URI_PREFIX}${RELEASE_PATH}${entityId}`);
    } catch (error) {
      // A related foundation entity WHO has no coded (MMS) form of is simply not offered.
      if (error instanceof PostcoordinationError && error.code === "CODE_NOT_FOUND") continue;
      throw error;
    }
    if (composite === null) {
      const directCode = related.code;
      const directTitle = plain(related.title);
      // WHO's own picker shows this as the exact composite, e.g. "JB64.4/BD54": the related chapter's category joined
      // with the stem code being annotated, not a separate WHO field.
      if (typeof directCode === "string" && directCode && directTitle) {
        composite = { code: `${directCode}/${selected.code}`, title: `${directTitle} / ${selected.title}`, uri: "" };
      }
    }
    const candidates: JsonRecord[] = [related];
    const children = listOrNull(related.child);
    if (!children) throw unavailable("related_children_malformed");
    for (const childUri of children.slice(0, MAX_OPTIONS)) candidates.push(await read.entity(childUri));
    truncated = truncated || children.length > MAX_OPTIONS;
    for (const candidate of candidates) {
      const candidateCode = candidate.code;
      const candidateTitle = plain(candidate.title);
      if (typeof candidateCode !== "string" || !candidateCode || !candidateTitle) continue;
      const scales = or(candidate.postcoordinationScale, []);
      terms.push({
        code: candidateCode,
        title: candidateTitle,
        uri: or(candidate["@id"], ""),
        requires_postcoordination: Array.isArray(scales) && scales.some((scale) => isRecord(scale) && isTrue(scale.requiredPostcoordination)),
      });
      if (terms.length >= MAX_OPTIONS) {
        truncated = true;
        break;
      }
    }
    if (terms.length >= MAX_OPTIONS) break;
  }
  return { schema_version: 1, release: WHO_RELEASE, selected, chapter, composite, terms, truncated };
}

async function codeDetails(read: Reader, code: unknown): Promise<GuidanceReply> {
  const [selected, entity] = await stem(read, await stemCode(read, code));
  const rawExclusions = or(entity.exclusion, []);
  const rawInclusions = or(entity.inclusion, []);
  if (!Array.isArray(rawExclusions) || !Array.isArray(rawInclusions)) throw unavailable("details_malformed");
  const exclusions: JsonRecord[] = [];
  for (const exclusion of rawExclusions.slice(0, MAX_OPTIONS)) {
    if (!isRecord(exclusion) || typeof exclusion.linearizationReference !== "string") continue;
    const excluded = await read.entity(exclusion.linearizationReference);
    exclusions.push({ code: or(excluded.code, ""), title: plain(exclusion.label) || plain(excluded.title) });
  }
  return {
    schema_version: 1,
    release: WHO_RELEASE,
    selected,
    definition: plain(entity.definition, 2000),
    coding_note: plain(entity.codingNote, 2000),
    fully_specified_name: plain(entity.fullySpecifiedName),
    inclusions: rawInclusions.slice(0, MAX_INCLUSIONS).flatMap((item) => (isRecord(item) && plain(item.label) ? [plain(item.label)] : [])),
    exclusions,
    truncated: rawExclusions.length > MAX_OPTIONS || rawInclusions.length > MAX_INCLUSIONS,
  };
}

export interface GuidanceOptions {
  /** Milliseconds on a monotonic clock (default `performance.now`); the 10-second budget runs on it. */
  now?: () => number;
}

export interface Guidance {
  /**
   * The reply of one guidance route for a request body (`{schema_version, ...fields}`), exactly the server's, or a
   * PostcoordinationError: INVALID_INPUT for a body that is not the route's exact field set, then the personal-data
   * boundary (PiiBoundaryError) on every string, then GUIDANCE_BUSY when two requests are already running.
   */
  answer(endpoint: GuidanceEndpoint, body: unknown): Promise<GuidanceReply>;
}

export function createGuidance(who: WhoEngineApi, { now = () => performance.now() }: GuidanceOptions = {}): Guidance {
  let running = 0;
  return {
    async answer(endpoint, body) {
      const fields = FIELDS[endpoint];
      if (!isRecord(body) || body.schema_version !== 1 || Object.keys(body).length !== fields.length + 1 || fields.some((field) => !(field in body))) {
        throw refuse("INVALID_INPUT", "The ICD-11 guidance request is invalid.");
      }
      for (const field of fields) {
        const value = body[field];
        if (typeof value === "string") assertNoPiiInText(value, field);
      }
      // guidance_request(): at most two guidance requests at once, so guidance never starves the coder's own search.
      if (running >= CAPACITY) throw refuse("GUIDANCE_BUSY", "WHO guidance is busy.", 429);
      running += 1;
      try {
        const read = reader(who, now);
        switch (endpoint) {
          case "postcoordination": return await postcoordination(read, body.code);
          case "postcoordination-options": return await postcoordinationOptions(read, body.stem_code, body.axis_id, body.parent_uri);
          case "hierarchy": return await hierarchy(read, body.code);
          case "related": return await relatedTerms(read, body.code, body.chapter);
          default: return await codeDetails(read, body.code);
        }
      } finally {
        running -= 1;
      }
    },
  };
}
