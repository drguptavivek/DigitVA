/** Terms search and code information (dorisTerminology.ts): the server's search_terms, search_context_from_entity and _codeinfo_item. */
import {
  codeinfoItem, postcoordinationAvailability, searchContextFromEntity, searchTerms, validSubtreeUris,
} from "../src/workspace/dorisTerminology";
import { WhoUnavailableError, type EntityRead, type WhoEngineApi } from "../src/workspace/whoEngineApi";

type Json = Record<string, any>;
const who = (overrides: Partial<WhoEngineApi> = {}): WhoEngineApi => ({
  search: async () => ({ entities: [], chopped: false }),
  codeinfo: async () => null,
  entity: async () => ({ kind: "absent", status: 404 }),
  title: async () => "",
  runProcessor: async () => ({ kind: "unavailable" }),
  ...overrides,
});

describe("validSubtreeUris", () => {
  const uri = "http://id.who.int/icd/release/11/2026-01/mms/979408586";

  it("accepts none and 1 to 40 WHO URIs of at most 200 characters without whitespace", () => {
    expect([undefined, null, [uri], Array(40).fill(uri)].every(validSubtreeUris)).toBe(true);
  });

  it("refuses an empty list, 41, a non-list, other hosts, whitespace, long and non-string entries", () => {
    const refused = [[], Array(41).fill(uri), "x", {}, ["https://id.who.int/icd/x"], ["http://other/icd/x"], [`${uri} x`], [`${uri}/${"1".repeat(200)}`], [5], [null], ["http://id.who.int/icd/"]];
    expect(refused.map(validSubtreeUris)).toEqual(refused.map(() => false));
  });
});

describe("postcoordinationAvailability", () => {
  it("keeps WHO's 0, 1 and 2 and nothing else", () => {
    expect([0, 1, 2].map(postcoordinationAvailability)).toEqual([
      { available: false, availability: 0 }, { available: true, availability: 1 }, { available: true, availability: 2 },
    ]);
    for (const other of [true, false, 3, -1, "1", null, undefined, 1.5]) {
      expect(postcoordinationAvailability(other)).toEqual({ available: false, availability: null });
    }
  });
});

describe("searchContextFromEntity", () => {
  it("derives the badges: required scale 2, optional scale 1, none 0", () => {
    const flags = { related_maternal: false, related_perinatal: false, has_coding_note: false };
    expect(searchContextFromEntity({})).toEqual({ postcoordination: false, postcoordination_availability: 0, ...flags });
    expect(searchContextFromEntity({ postcoordinationScale: [] })).toEqual({ postcoordination: false, postcoordination_availability: 0, ...flags });
    expect(searchContextFromEntity({ postcoordinationScale: [{ requiredPostcoordination: false }, "x"] })).toMatchObject({ postcoordination: true, postcoordination_availability: 1 });
    expect(searchContextFromEntity({ postcoordinationScale: [{ requiredPostcoordination: "false" }, { requiredPostcoordination: true }] })).toMatchObject({ postcoordination_availability: 2 });
    expect(searchContextFromEntity({ postcoordinationScale: [{ requiredPostcoordination: "true" }] })).toMatchObject({ postcoordination_availability: 2 });
  });

  it("reads the related-chapter and coding-note flags by Python truthiness", () => {
    expect(searchContextFromEntity({
      relatedEntitiesInMaternalChapter: ["http://x"], relatedEntitiesInPerinatalChapter: [], codingNote: { "@language": "en", "@value": "" },
    })).toMatchObject({ related_maternal: true, related_perinatal: false, has_coding_note: true });
    expect(searchContextFromEntity({ codingNote: "" })).toMatchObject({ has_coding_note: false });
  });

  it("is unavailable when the scale is not a list", () => {
    expect(() => searchContextFromEntity({ postcoordinationScale: "x" })).toThrow(WhoUnavailableError);
  });
});

describe("searchTerms", () => {
  const entity = (overrides: Json = {}): Json => ({
    theCode: "BA41.Z", id: "http://id.who.int/icd/release/11/2026-01/mms/1", title: "<em class='found'>Acute</em> myocardial infarction",
    postcoordinationAvailability: 1, hasMaternalChapterLink: true, hasPerinatalChapterLink: false, hasCodingNote: true, ...overrides,
  });
  const search = (entities: unknown[], chopped: unknown = false, limit = 20) =>
    searchTerms(who({ search: async () => ({ entities, chopped }) }), "myocard", { limit });

  it("builds the server's term from a WHO entity and always asks the engine for 20", async () => {
    const spy = jest.fn(async () => ({ entities: [entity()], chopped: false }));
    const reply = await searchTerms(who({ search: spy }), "myocard", { limit: 3, subtreeUris: ["http://id.who.int/icd/entity/1"] });
    expect(spy).toHaveBeenCalledWith("myocard", { limit: 20, subtreeUris: ["http://id.who.int/icd/entity/1"] });
    expect(reply).toEqual({
      truncated: false,
      items: [{
        code: "BA41.Z", title: "Acute myocardial infarction", uri: "http://id.who.int/icd/release/11/2026-01/mms/1", release: "2026-01",
        matching_text: "Acute myocardial infarction", postcoordination: true, postcoordination_availability: 1,
        related_maternal: true, related_perinatal: false, has_coding_note: true,
      }],
    });
  });

  it("falls back across code, uri and title fields, and skips what has no code, uri or title", async () => {
    const reply = await search([
      entity({ theCode: undefined, code: "C1", id: undefined, uri: "u1" }),
      entity({ theCode: "", code: "C2", id: "", uri: "", "@id": "u2" }),
      entity({ theCode: "C3", title: "", titleWithoutCodes: "Plain title" }),
      entity({ theCode: "", code: "" }),
      entity({ id: undefined }),
      entity({ title: "", titleWithoutCodes: "" }),
      entity({ theCode: 5 }),
      "not an entity",
      null,
    ]);
    expect(reply.items.map((item) => [item.code, item.uri, item.title])).toEqual([
      ["C1", "u1", "Acute myocardial infarction"], ["C2", "u2", "Acute myocardial infarction"], ["C3", "http://id.who.int/icd/release/11/2026-01/mms/1", "Plain title"],
    ]);
    expect(reply.truncated).toBe(true); // six entities were not usable, as on the server
  });

  it("reads the matching text from matchingPVs strings, else matchingText, else the title", async () => {
    const reply = await search([
      entity({ matchingPVs: ["heart", 5, "attack"] }),
      entity({ matchingPVs: [{ label: "object" }], matchingText: "ignored" }),
      entity({ matchingPVs: [], matchingText: "<b>text</b>" }),
      entity({ matchingText: { "@value": "valued" } }),
      entity({ matchingText: 7 }),
    ]);
    expect(reply.items.map((item) => item.matching_text)).toEqual(["heart attack", "Acute myocardial infarction", "text", "valued", "Acute myocardial infarction"]);
  });

  it("reads the flags strictly and the availability as WHO's number", async () => {
    const reply = await search([entity({ postcoordinationAvailability: 2, hasMaternalChapterLink: "yes", hasPerinatalChapterLink: true, hasCodingNote: 1 }), entity({ postcoordinationAvailability: true }), entity({ postcoordinationAvailability: 0 })]);
    expect(reply.items.map((item) => [item.postcoordination, item.postcoordination_availability, item.related_maternal, item.related_perinatal, item.has_coding_note])).toEqual([
      [true, 2, false, true, false], [false, null, true, false, true], [false, 0, true, false, true],
    ]);
  });

  it("stops at the limit and says truncated when WHO had more or cut the list", async () => {
    const many = Array.from({ length: 5 }, (_unused, index) => entity({ theCode: `C${index}` }));
    const cut = await search(many, false, 2);
    expect(cut.items.map((item) => item.code)).toEqual(["C0", "C1"]);
    expect(cut.truncated).toBe(true);
    expect((await search(many.slice(0, 2), false, 2)).truncated).toBe(false);
    expect((await search(many.slice(0, 2), true, 2)).truncated).toBe(true);
    expect((await search(many.slice(0, 2), "yes", 2)).truncated).toBe(true);
    expect((await search(many.slice(0, 2), 0, 2)).truncated).toBe(false);
  });

  it("passes the client's unavailability on", async () => {
    await expect(searchTerms(who({ search: async () => { throw new WhoUnavailableError("search_failed"); } }), "ab", { limit: 20 })).rejects.toThrow(WhoUnavailableError);
  });
});

describe("codeinfoItem", () => {
  const stemUri = "http://id.who.int/icd/release/11/2026-01/mms/1334938734/unspecified";
  const ok = (entity: Json): EntityRead => ({ kind: "ok", entity });
  const record: Record<string, Json | null> = {
    "BA41.Z": { code: "BA41.Z", stemId: stemUri },
    "1B12.2": { code: "1B12.2", stemId: "http://id.who.int/icd/release/11/2026-01/mms/2" },
    XA0G74: { code: "XA0G74", stemId: "http://id.who.int/icd/release/11/2026-01/mms/3" },
    "1B12.2&XA0G74": { code: "1B12.2&XA0G74", stemId: "http://id.who.int/icd/release/11/2026-01/mms/2" },
  };
  const client = (entity: EntityRead, codeinfo: Record<string, Json | null> = record) =>
    who({ codeinfo: async (code) => codeinfo[code] ?? null, entity: async () => entity });

  it("builds a stem item with the entity's title and badges", async () => {
    const entity = ok({
      title: { "@language": "en", "@value": "Acute myocardial infarction, unspecified" },
      postcoordinationScale: [{ requiredPostcoordination: false }], relatedEntitiesInMaternalChapter: ["x"], codingNote: { "@value": "n" },
    });
    await expect(codeinfoItem(client(entity), "BA41.Z")).resolves.toEqual({
      code: "BA41.Z", title: "Acute myocardial infarction, unspecified", uri: stemUri, release: "2026-01",
      postcoordination: true, postcoordination_availability: 1, related_maternal: true, related_perinatal: false, has_coding_note: true,
    });
  });

  it("uses codeinfo's own title or label first, and carries no badges for an expression", async () => {
    const entity = ok({ title: "Entity title", postcoordinationScale: [{ requiredPostcoordination: true }] });
    const withTitle = client(entity, { ...record, "BA41.Z": { ...record["BA41.Z"], title: "Own <b>title</b>" } });
    expect((await codeinfoItem(withTitle, "BA41.Z"))?.title).toBe("Own title");
    const withLabel = client(entity, { ...record, "BA41.Z": { ...record["BA41.Z"], label: { "@value": "Own label" } } });
    expect((await codeinfoItem(withLabel, "BA41.Z"))?.title).toBe("Own label");
    expect((await codeinfoItem(client(ok({ label: "Entity label" })), "BA41.Z"))?.title).toBe("Entity label");
    await expect(codeinfoItem(client(entity), "1B12.2&XA0G74")).resolves.toEqual({
      code: "1B12.2&XA0G74", title: "Entity title", release: "2026-01", postcoordination: false,
      uri: "http://id.who.int/icd/release/11/2026-01/mms/2 & http://id.who.int/icd/release/11/2026-01/mms/3",
    });
    const slash = await codeinfoItem(client(entity, { ...record, "1B12.2/XA0G74": { code: "1B12.2/XA0G74", stemId: stemUri } }), "1B12.2/XA0G74");
    expect(slash).toMatchObject({ uri: "http://id.who.int/icd/release/11/2026-01/mms/2 / http://id.who.int/icd/release/11/2026-01/mms/3", postcoordination: false });
    expect(slash).not.toHaveProperty("postcoordination_availability");
  });

  it("is null when WHO does not know the code, a part, a stem URI, a stem entity or any title", async () => {
    const entity = ok({ title: "T" });
    await expect(codeinfoItem(client(entity), "UNKNOWN")).resolves.toBeNull();
    await expect(codeinfoItem(client(entity, { "BA41.Z": { code: "OTHER", stemId: stemUri } }), "BA41.Z")).resolves.toBeNull();
    await expect(codeinfoItem(client(entity, { "BA41.Z": { code: "BA41.Z" } }), "BA41.Z")).resolves.toBeNull();
    await expect(codeinfoItem(client(entity, { "BA41.Z": { code: "BA41.Z", stemId: "http://elsewhere/1" } }), "BA41.Z")).resolves.toBeNull();
    await expect(codeinfoItem(client({ kind: "absent", status: 404 }), "BA41.Z")).resolves.toBeNull();
    await expect(codeinfoItem(client(ok({ title: "" })), "BA41.Z")).resolves.toBeNull();
    await expect(codeinfoItem(client(ok({})), "BA41.Z")).resolves.toBeNull();
  });

  it("passes the client's unavailability on, from codeinfo, the entity or the scale", async () => {
    const boom = () => { throw new WhoUnavailableError("down"); };
    await expect(codeinfoItem(who({ codeinfo: boom }), "BA41.Z")).rejects.toThrow(WhoUnavailableError);
    await expect(codeinfoItem(who({ codeinfo: async () => record["BA41.Z"], entity: boom }), "BA41.Z")).rejects.toThrow(WhoUnavailableError);
    await expect(codeinfoItem(client(ok({ title: "T", postcoordinationScale: "bad" })), "BA41.Z")).rejects.toThrow(WhoUnavailableError);
  });
});
