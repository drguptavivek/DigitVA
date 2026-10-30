/**
 * The offline picker guidance routes (dorisGuidance.ts, a port of icd11_postcoordination.py's postcoordination,
 * options, hierarchy, related and details) over a fake WHO client with synthetic entities: caps and truncation, the
 * 48-read budget and 10-second deadline, GUIDANCE_BUSY, every refusal, the X-chapter "other postcoordination", related
 * terms that WHO has no coded form of, and the editor/requester wiring. The recorded WHO replies are replayed in
 * offline-who-golden.test.ts.
 */
import { ApiError } from "../src/api";
import type { OfflineEngine } from "../src/offlineEngine";
import { dorisGuidance, parseDorisDetails, parseDorisHierarchy, parseDorisOptions, parseDorisPostcoordination, parseDorisRelated } from "../src/workspace/doris/guidance";
import { createGuidance, GUIDANCE_ENDPOINTS, PostcoordinationError, X_CHAPTER_URI, type GuidanceEndpoint } from "../src/workspace/dorisGuidance";
import { createGuidanceRequester, createOfflineDorisEditor } from "../src/workspace/offlineDoris";
import { PiiBoundaryError } from "../src/workspace/piiBoundary";
import { WhoUnavailableError, type EntityRead, type WhoEngineApi } from "../src/workspace/whoEngineApi";
import type { JsonRecord } from "../src/workspace/whoText";

jest.mock("expo-crypto", () => ({
  CryptoDigestAlgorithm: { SHA256: "SHA-256" },
  digestStringAsync: async () => "0".repeat(64),
  randomUUID: () => "00000000-0000-4000-8000-000000000000",
}));

const mms = (id: string | number) => `http://id.who.int/icd/release/11/2026-01/mms/${id}`;
const fnd = (id: string | number) => `http://id.who.int/icd/entity/${id}`;

type Entities = Record<string, JsonRecord | number>;
/** A WHO client over plain maps. An entity that is a number is WHO's answer with that status; a missing one is a 404. */
function fakeWho(entities: Entities, codeinfos: Record<string, JsonRecord | null | "fail"> = {}) {
  const reads: string[] = [];
  const who: WhoEngineApi = {
    search: async () => { throw new Error("search is not a guidance read"); },
    codeinfo: async (expression) => {
      reads.push(`codeinfo ${expression}`);
      const found = codeinfos[expression];
      if (found === "fail") throw new WhoUnavailableError("codeinfo_failed");
      return found ?? null;
    },
    entity: async (uri): Promise<EntityRead> => {
      reads.push(uri);
      const found = entities[uri];
      if (found === undefined) return { kind: "absent", status: 404 };
      return typeof found === "number" ? { kind: "absent", status: found } : { kind: "ok", entity: found };
    },
    title: async () => "",
    runProcessor: async () => ({ kind: "unavailable" }),
  };
  return { who, reads };
}

const title = (value: string) => ({ "@language": "en", "@value": value });
const stemInfo = (code: string, id: string | number, extra: JsonRecord = {}) => ({ code, stemId: mms(id), ...extra });
const entityOf = (code: string, name: string, extra: JsonRecord = {}): JsonRecord => ({ code, title: title(name), ...extra });
const scale = (axis: string, roots: string[], extra: JsonRecord = {}) => ({
  axisName: `http://id.who.int/icd/schema/${axis}`,
  scaleEntity: roots,
  requiredPostcoordination: "false",
  allowMultipleValues: "AllowAlways",
  ...extra,
});

async function refusal(promise: Promise<unknown>): Promise<PostcoordinationError> {
  const error = await promise.then(() => null, (thrown: unknown) => thrown);
  expect(error).toBeInstanceOf(PostcoordinationError);
  return error as PostcoordinationError;
}
const expectRefusal = async (promise: Promise<unknown>, code: string, status = 422) => {
  const error = await refusal(promise);
  expect({ code: error.code, status: error.status }).toEqual({ code, status });
  return error;
};

const ask = (who: WhoEngineApi, endpoint: GuidanceEndpoint, fields: JsonRecord, options?: { now?: () => number }) =>
  createGuidance(who, options).answer(endpoint, { schema_version: 1, ...fields });

/** A stem `ST01` with a scale and the roots it names. */
function stemWorld(extra: JsonRecord = {}, more: Entities = {}) {
  return fakeWho(
    { [mms(1)]: entityOf("ST01", "Stem <b>one</b>", { classKind: "category", ...extra }), ...more },
    { ST01: stemInfo("ST01", 1) },
  );
}

describe("postcoordination", () => {
  it("builds the stem and axes in WHO's order, with the server's labels, instructions and flags", async () => {
    const { who } = stemWorld(
      {
        postcoordinationScale: [
          scale("hasCausingCondition", [mms(10), mms(11)], { requiredPostcoordination: true, allowMultipleValues: "NotAllowed" }),
          scale("specificAnatomy", [mms(12)], { requiredPostcoordination: "true", allowMultipleValues: "AllowedExceptFromSameBlock" }),
          scale("severity", [mms(13)]),
        ],
      },
      {
        [mms(10)]: entityOf("AA00", "Causing", { child: [mms(20)] }),
        [mms(11)]: entityOf("", "Window with no code", { child: [] }), // an uncoded leaf: skipped, its root still listed
        [mms(12)]: entityOf("", "Block", { child: [mms(21)] }), // uncoded with children: kept
        [mms(13)]: entityOf("BB00", "Mild"),
      },
    );
    const reply = await ask(who, "postcoordination", { code: "ST01" }) as any;
    expect(reply).toEqual({
      schema_version: 1,
      release: "2026-01",
      stem: { code: "ST01", title: "Stem one", uri: mms(1) },
      axes: [
        {
          id: "hasCausingCondition", label: "Has causing condition", required: true, instruction: "code also", allow_multiple: false,
          allow_multiple_values: "NotAllowed", options: [{ code: "AA00", title: "Causing", uri: mms(10), has_children: true, block_uri: mms(10) }],
          subtree_uris: [mms(10), mms(11)], truncated: false,
        },
        {
          id: "specificAnatomy", label: "Specific anatomy", required: true, instruction: "use additional code", allow_multiple: true,
          allow_multiple_values: "AllowedExceptFromSameBlock", options: [{ code: "", title: "Block", uri: mms(12), has_children: true, block_uri: mms(12) }],
          subtree_uris: [mms(12)], truncated: false,
        },
        {
          id: "severity", label: "Severity", required: false, instruction: "use additional code, if desired", allow_multiple: true,
          allow_multiple_values: "AllowAlways", options: [{ code: "BB00", title: "Mild", uri: mms(13), has_children: false, block_uri: mms(13) }],
          subtree_uris: [mms(13)], truncated: false,
        },
      ],
      other_postcoordination: { subtree_uris: [X_CHAPTER_URI] },
      truncated: false,
    });
  });

  it("reads a root whose children WHO sends as something other than a list as having none", async () => {
    const { who } = stemWorld({ postcoordinationScale: [scale("severity", [mms(10)])] }, { [mms(10)]: entityOf("BB00", "Mild", { child: "no" }) });
    expect((await ask(who, "postcoordination", { code: "ST01" }) as any).axes[0].options).toEqual([
      { code: "BB00", title: "Mild", uri: mms(10), has_children: false, block_uri: mms(10) },
    ]);
  });

  it("caps an axis at 12 roots and says so", async () => {
    const roots = Array.from({ length: 14 }, (_, index) => mms(100 + index));
    const options = Object.fromEntries(roots.map((uri, index) => [uri, entityOf(`C${index}`, `Option ${index}`)]));
    const { who } = stemWorld({ postcoordinationScale: [scale("severity", roots)] }, options);
    const [axis] = (await ask(who, "postcoordination", { code: "ST01" }) as any).axes;
    expect(axis.options).toHaveLength(12);
    expect(axis.subtree_uris).toEqual(roots.slice(0, 12));
    expect(axis.truncated).toBe(true);
  });

  it("offers other postcoordination only for a category stem that is not an extension code", async () => {
    const other = async (code: string, extra: JsonRecord) => {
      const { who } = fakeWho({ [mms(1)]: entityOf(code, "Stem", extra) }, { [code]: stemInfo(code, 1) });
      return (await ask(who, "postcoordination", { code }) as any).other_postcoordination;
    };
    expect(await other("XA01", { classKind: "category" })).toBeNull();
    expect(await other("ST01", { classKind: "block" })).toBeNull();
    expect(await other("ST01", {})).toBeNull();
    expect(await other("ST01", { classKind: "category" })).toEqual({ subtree_uris: [X_CHAPTER_URI] });
  });

  it("reads a stem with no scale as no axes", async () => {
    const { who } = stemWorld({ postcoordinationScale: [] });
    expect(await ask(who, "postcoordination", { code: "ST01" })).toMatchObject({ axes: [], truncated: false });
  });

  it("refuses more than 12 axes with GUIDANCE_LIMIT, and a malformed scale as unavailable", async () => {
    const many = Array.from({ length: 13 }, (_, index) => scale(`axis${index}`, []));
    await expectRefusal(ask(stemWorld({ postcoordinationScale: many }).who, "postcoordination", { code: "ST01" }), "GUIDANCE_LIMIT", 503);
    const malformed: JsonRecord[] = [
      { postcoordinationScale: "no" },
      { postcoordinationScale: ["no"] },
      { postcoordinationScale: [scale("a", [], { axisName: 7 })] },
      { postcoordinationScale: [scale("a", "x" as unknown as string[])] },
      { postcoordinationScale: [scale("a", [], { requiredPostcoordination: "maybe" })] },
      { postcoordinationScale: [scale("a", [], { allowMultipleValues: "Sometimes" })] },
      { postcoordinationScale: [scale("9axis", [])] },
      { postcoordinationScale: [scale("has-dash", [])] },
    ];
    for (const extra of malformed) {
      await expect(ask(stemWorld(extra).who, "postcoordination", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    }
  });

  it("is unavailable when a root's metadata is incomplete", async () => {
    for (const root of [entityOf("A", ""), entityOf("", ""), { title: title("No code field"), child: [mms(1)] }, { code: 7, title: title("Code is a number") }]) {
      const { who } = stemWorld({ postcoordinationScale: [scale("severity", [mms(10)])] }, { [mms(10)]: root });
      await expect(ask(who, "postcoordination", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    }
  });
});

describe("stem checks and the read budget", () => {
  it("refuses a code that is not one valid stem code, one WHO does not know, or whose entity does not match", async () => {
    const { who } = stemWorld({ postcoordinationScale: [] });
    for (const code of [7, "", "lower", "A".repeat(129), " ST01", "ST01\n"]) {
      const error = await expectRefusal(ask(who, "postcoordination", { code }), "INVALID_INPUT");
      expect(error.message).toBe("Select one valid ICD-11 stem code.");
    }
    expect((await expectRefusal(ask(who, "postcoordination", { code: "ZZ99" }), "CODE_NOT_FOUND")).message).toBe("ICD-11 stem code was not found.");
    const mismatch = fakeWho({ [mms(1)]: entityOf("OTHER", "x") }, { ST01: stemInfo("ST01", 1), WRONG: stemInfo("WRONG-CODE", 1) });
    expect((await expectRefusal(ask(mismatch.who, "postcoordination", { code: "ST01" }), "CODE_NOT_FOUND")).message).toBe("ICD-11 stem metadata did not match.");
    await expectRefusal(ask(mismatch.who, "postcoordination", { code: "WRONG" }), "CODE_NOT_FOUND");
    const noStem = fakeWho({}, { ST01: { code: "ST01" } });
    expect((await expectRefusal(ask(noStem.who, "postcoordination", { code: "ST01" }), "INVALID_URI")).message).toBe("Invalid WHO entity URI.");
  });

  it("maps a WHO 404 to CODE_NOT_FOUND and any other unusable entity answer to unavailable", async () => {
    const missing = fakeWho({}, { ST01: stemInfo("ST01", 1) });
    expect((await expectRefusal(ask(missing.who, "postcoordination", { code: "ST01" }), "CODE_NOT_FOUND")).message).toBe("WHO entity was not found.");
    for (const status of [400, 500, 200]) {
      const bad = fakeWho({ [mms(1)]: status }, { ST01: stemInfo("ST01", 1) });
      await expect(ask(bad.who, "postcoordination", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    }
  });

  it("lets a failing WHO client through untouched", async () => {
    const down = fakeWho({}, { ST01: "fail" });
    await expect(ask(down.who, "postcoordination", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
  });

  it("allows 48 reads and refuses the 49th with GUIDANCE_LIMIT", async () => {
    // codeinfo + stem = 2 reads, then one read per root option.
    const build = (roots: number) => {
      const uris = Array.from({ length: roots }, (_, index) => mms(100 + index));
      return stemWorld(
        { postcoordinationScale: [scale("a", uris.slice(0, 12)), scale("b", uris.slice(12, 24)), scale("c", uris.slice(24, 36)), scale("d", uris.slice(36))] },
        Object.fromEntries(uris.map((uri, index) => [uri, entityOf(`C${index}`, `Option ${index}`)])),
      );
    };
    const { who, reads } = build(46);
    expect((await ask(who, "postcoordination", { code: "ST01" }) as any).axes).toHaveLength(4);
    expect(reads).toHaveLength(48);
    const over = build(47);
    const error = await expectRefusal(ask(over.who, "postcoordination", { code: "ST01" }), "GUIDANCE_LIMIT", 503);
    expect(error.message).toBe("WHO guidance exceeded its request limit.");
  });

  it("counts a read the client answers from its cache, as the server's budget counts each WHO read", async () => {
    const cached = Array.from({ length: 25 }, () => mms(100));
    const { who } = stemWorld({ postcoordinationScale: [scale("a", cached.slice(0, 12)), scale("b", cached.slice(12))] }, { [mms(100)]: entityOf("C", "Same") });
    // 2 + 25 reads fit; the same entity twice is two reads of the budget.
    expect((await ask(who, "postcoordination", { code: "ST01" }) as any).axes[1].options).toHaveLength(12);
    const more = stemWorld(
      { postcoordinationScale: [scale("a", cached.slice(0, 12)), scale("b", cached.slice(0, 12)), scale("c", cached.slice(0, 12)), scale("d", cached.slice(0, 12))] },
      { [mms(100)]: entityOf("C", "Same") },
    );
    await expectRefusal(ask(more.who, "postcoordination", { code: "ST01" }), "GUIDANCE_LIMIT", 503);
  });

  it("refuses a read after 10 seconds", async () => {
    const { who } = stemWorld({ postcoordinationScale: [] });
    const times = [0, 5_000, 10_001];
    const now = jest.fn(() => times.shift() ?? 99_999);
    await expectRefusal(ask(who, "postcoordination", { code: "ST01" }, { now }), "GUIDANCE_LIMIT", 503);
    // exactly at the deadline is still inside it
    const edge = [0, 1, 10_000];
    expect(await ask(stemWorld({ postcoordinationScale: [] }).who, "postcoordination", { code: "ST01" }, { now: () => edge.shift() ?? 10_000 })).toMatchObject({ axes: [] });
  });

  it("validates every URI before reading it", async () => {
    const bad = [
      7, "", "x".repeat(401), "https://id.who.int/icd/release/11/2026-01/mms/5", "http://evil.example/icd/release/11/2026-01/mms/5",
      "http://id.who.int.evil/icd/release/11/2026-01/mms/5", "http://id.who.int/icd/release/11/2025-01/mms/5", `${mms(5)}?x=1`, `${mms(5)}#frag`,
      `${mms(5)}/`, `${mms(5)}/residual`, mms("abc"), "http://id.who.int/icd/entity/5", "http://id.who.int/icd/release/11/2026-01/mms",
    ];
    for (const uri of bad) {
      const info = { ST01: { code: "ST01", stemId: uri } };
      const { who, reads } = fakeWho({}, info as any);
      await expectRefusal(ask(who, "postcoordination", { code: "ST01" }), "INVALID_URI");
      expect(reads).toEqual(["codeinfo ST01"]);
    }
    // the scheme may be any case and extra slashes are dropped, as urlsplit does; the entity is read by its canonical URI
    for (const uri of [mms(5).replace("http", "HTTP"), mms(5).replace("id.who.int/", "id.who.int//"), `${mms(5)}/unspecified`, `${mms(5)}/other`]) {
      const { who, reads } = fakeWho({ [uri.includes("/other") || uri.includes("unspecified") ? uri : mms(5)]: entityOf("ST01", "x", { postcoordinationScale: [] }) }, { ST01: { code: "ST01", stemId: uri } });
      await ask(who, "postcoordination", { code: "ST01" });
      expect(reads[1]).toMatch(/^http:\/\/id\.who\.int\/icd\/release\/11\/2026-01\/mms\/5/);
    }
  });
});

describe("postcoordination-options", () => {
  const root = mms(10);
  const base = (extra: Entities = {}, scales: unknown = [scale("hasCausingCondition", [root, mms(11)])]) =>
    stemWorld({ postcoordinationScale: scales }, { [root]: entityOf("AA00", "Root", { child: [mms(20), mms(21), mms(22)] }), ...extra });
  const request = (parent: unknown, axis: unknown = "hasCausingCondition", stem: unknown = "ST01") => ({ stem_code: stem, axis_id: axis, parent_uri: parent });

  it("lists the children of a root, skipping uncoded leaves, with the root as their block", async () => {
    const { who } = base({
      [mms(20)]: entityOf("AA01", "One", { child: [mms(30)] }),
      [mms(21)]: entityOf("", "Uncoded leaf"),
      [mms(22)]: entityOf("AA02", "Two"),
    });
    expect(await ask(who, "postcoordination-options", request(root))).toEqual({
      schema_version: 1,
      release: "2026-01",
      stem: { code: "ST01", title: "Stem one", uri: mms(1) },
      axis_id: "hasCausingCondition",
      parent_uri: root,
      items: [
        { code: "AA01", title: "One", uri: mms(20), has_children: true, block_uri: root },
        { code: "AA02", title: "Two", uri: mms(22), has_children: false, block_uri: root },
      ],
      truncated: false,
    });
  });

  it("walks up from a deeper parent to its root, and reads 12 children at most", async () => {
    const kids = Array.from({ length: 13 }, (_, index) => mms(200 + index));
    const { who } = base({
      [mms(20)]: entityOf("AA01", "One", { parent: [mms(10)], child: kids }),
      ...Object.fromEntries(kids.map((uri, index) => [uri, entityOf(`K${index}`, `Kid ${index}`)])),
    });
    const reply = await ask(who, "postcoordination-options", request(mms(20))) as any;
    expect(reply.items).toHaveLength(12);
    expect(reply.truncated).toBe(true);
    expect(reply.items.every((item: any) => item.block_uri === root)).toBe(true);
  });

  it("refuses an axis the stem does not have, a parent outside the axis, and a bad parent URI", async () => {
    const { who } = base({ [mms(20)]: entityOf("AA01", "One", { parent: [mms(30)] }), [mms(30)]: entityOf("ZZ", "Top") });
    for (const axis of ["noSuchAxis", 7, null]) await expectRefusal(ask(who, "postcoordination-options", request(root, axis)), "INVALID_AXIS");
    const odd = base({}, ["not a record", { axisName: 5 }, scale("other", [root])]);
    await expectRefusal(ask(odd.who, "postcoordination-options", request(root)), "INVALID_AXIS");
    // mms(20) -> mms(30) -> no parent
    await expectRefusal(ask(who, "postcoordination-options", request(mms(20))), "INVALID_PARENT");
    const noParents = base({ [mms(20)]: entityOf("AA01", "One", { parent: "no" }) });
    await expectRefusal(ask(noParents.who, "postcoordination-options", request(mms(20))), "INVALID_PARENT");
    const missingParent = base({ [mms(20)]: entityOf("AA01", "One") });
    await expectRefusal(ask(missingParent.who, "postcoordination-options", request(mms(20))), "INVALID_PARENT");
    for (const parent of [7, "http://id.who.int/icd/entity/10", `${root}?x`]) await expectRefusal(ask(who, "postcoordination-options", request(parent)), "INVALID_URI");
    const badStep = base({ [mms(20)]: entityOf("AA01", "One", { parent: ["http://elsewhere/x"] }) });
    await expectRefusal(ask(badStep.who, "postcoordination-options", request(mms(20))), "INVALID_URI");
  });

  it("gives up after 12 steps up", async () => {
    const chain: Entities = {};
    for (let index = 0; index < 14; index += 1) chain[mms(300 + index)] = entityOf(`P${index}`, `Level ${index}`, { parent: [mms(301 + index)] });
    const { who } = base(chain);
    await expectRefusal(ask(who, "postcoordination-options", request(mms(300))), "INVALID_PARENT");
    // 12 steps still reach a root at the 12th parent (steps 0..11 test it before moving), so one more is refused
    const near: Entities = {};
    for (let index = 0; index < 11; index += 1) near[mms(300 + index)] = entityOf(`P${index}`, `Level ${index}`, { parent: [index === 10 ? root : mms(301 + index)] });
    const ok = base(near);
    expect(await ask(ok.who, "postcoordination-options", request(mms(300)))).toMatchObject({ items: expect.any(Array) });
  });

  it("is unavailable for malformed scales, roots and children, and for an option without metadata", async () => {
    await expect(ask(base({}, "no").who, "postcoordination-options", request(root))).rejects.toThrow(WhoUnavailableError);
    const badRoots = base({}, [{ axisName: "a/hasCausingCondition", scaleEntity: "no" }]);
    await expect(ask(badRoots.who, "postcoordination-options", request(root))).rejects.toThrow(WhoUnavailableError);
    const badKids = base({ [root]: entityOf("AA00", "Root", { child: "no" }) });
    await expect(ask(badKids.who, "postcoordination-options", request(root))).rejects.toThrow(WhoUnavailableError);
    const incomplete = base({ [mms(20)]: entityOf("AA01", "") });
    await expect(ask(incomplete.who, "postcoordination-options", request(root))).rejects.toThrow(WhoUnavailableError);
  });

  it("refuses a stem it cannot find", async () => {
    await expectRefusal(ask(base().who, "postcoordination-options", request(root, "hasCausingCondition", "ZZ99")), "CODE_NOT_FOUND");
  });
});

describe("hierarchy", () => {
  /** Chapter 11 > block 11A > ST01 (with two siblings and three children). */
  const world = (selfExtra: JsonRecord = {}, more: Entities = {}, codeinfos: Record<string, JsonRecord | null> = {}) => fakeWho(
    {
      [mms(1)]: entityOf("ST01", "Stem", { parent: [mms(2)], child: [mms(5), mms(6)], ...selfExtra }),
      [mms(2)]: entityOf("11A", "Block", { parent: [mms(3)], child: [mms(1), mms(7), mms(8)] }),
      [mms(3)]: entityOf("11", "Chapter", { parent: [mms("")].map(() => "http://id.who.int/icd/release/11/2026-01/mms") }),
      [mms(5)]: entityOf("ST01.0", "Child zero"),
      [mms(6)]: entityOf("ST01.1", "Child one", { child: [mms(9)] }),
      [mms(7)]: entityOf("ST02", "Sibling"),
      [mms(8)]: entityOf("ST03", "Another sibling"),
      ...more,
    },
    { ST01: stemInfo("ST01", 1), ...codeinfos },
  );

  it("returns ancestors from the top, the siblings, the children, terms and the related chapters", async () => {
    const { who } = world({
      indexTerm: [{ label: title("Term <i>A</i>") }, { label: title("") }, "no", { label: title("Term B") }],
      relatedEntitiesInMaternalChapter: [fnd(50)],
      relatedEntitiesInPerinatalChapter: [fnd(51)],
    }, { [fnd(50)]: entityOf("JB64", "Maternal"), [fnd(51)]: { title: title("Perinatal, no code") } });
    expect(await ask(who, "hierarchy", { code: "ST01" })).toEqual({
      schema_version: 1,
      release: "2026-01",
      selected: { code: "ST01", title: "Stem", uri: mms(1) },
      selected_expression: null,
      ancestors: [{ code: "11", title: "Chapter", uri: mms(3) }, { code: "11A", title: "Block", uri: mms(2) }],
      siblings: [
        { code: "ST02", title: "Sibling", uri: mms(7), has_children: false },
        { code: "ST03", title: "Another sibling", uri: mms(8), has_children: false },
      ],
      children: [
        { code: "ST01.0", title: "Child zero", uri: mms(5), has_children: false },
        { code: "ST01.1", title: "Child one", uri: mms(6), has_children: true },
      ],
      matching_terms: ["Term A", "Term B"],
      related_maternal: [{ code: "JB64", title: "Maternal", uri: fnd(50) }],
      related_perinatal: [{ code: "", title: "Perinatal, no code", uri: fnd(51) }],
      truncated: false,
    });
  });

  it("answers an expression through its stem, with the expression echoed", async () => {
    const { who, reads } = world({}, {}, { "ST01&XA00": { code: "ST01&XA00", stemCode: "ST01" } });
    const reply = await ask(who, "hierarchy", { code: "ST01&XA00" }) as any;
    expect(reply.selected_expression).toEqual({ code: "ST01&XA00", stem_code: "ST01" });
    expect(reads.slice(0, 2)).toEqual(["codeinfo ST01&XA00", "codeinfo ST01"]);
  });

  it("refuses an expression that is malformed, unknown, or without a stem", async () => {
    const { who } = world({}, {}, { "ST01&XA00": { code: "OTHER" }, "ST01/XB00": { code: "ST01/XB00" }, "ST01/XC00": { code: "ST01/XC00", stemCode: 7 } });
    expect((await expectRefusal(ask(who, "hierarchy", { code: "st01&x" }), "INVALID_INPUT")).message).toBe("Select a valid ICD-11 expression.");
    expect((await expectRefusal(ask(who, "hierarchy", { code: "ST01&XA00" }), "CODE_NOT_FOUND")).message).toBe("ICD-11 expression was not found.");
    await expectRefusal(ask(who, "hierarchy", { code: "ST09&XA00" }), "CODE_NOT_FOUND");
    await expect(ask(who, "hierarchy", { code: "ST01/XB00" })).rejects.toThrow(WhoUnavailableError);
    await expect(ask(who, "hierarchy", { code: "ST01/XC00" })).rejects.toThrow(WhoUnavailableError);
    await expectRefusal(ask(who, "hierarchy", { code: 7 }), "INVALID_INPUT");
  });

  it("stops the ancestor walk at the root, at a repeat, at a missing or malformed parent, and after 12", async () => {
    const top = world({ parent: [] });
    expect((await ask(top.who, "hierarchy", { code: "ST01" }) as any).ancestors).toEqual([]);
    const odd = world({ parent: "no" });
    expect((await ask(odd.who, "hierarchy", { code: "ST01" }) as any).ancestors).toEqual([]);
    const loop = world({}, { [mms(2)]: entityOf("11A", "Block", { parent: [mms(1)], child: [mms(1)] }) });
    expect((await ask(loop.who, "hierarchy", { code: "ST01" }) as any).ancestors).toEqual([{ code: "11A", title: "Block", uri: mms(2) }]);
    const chain: Entities = {};
    for (let index = 0; index < 15; index += 1) chain[mms(400 + index)] = entityOf(`A${index}`, `Level ${index}`, { parent: [mms(401 + index)], child: [mms(1)] });
    const deep = world({ parent: [mms(400)] }, chain);
    const reply = await ask(deep.who, "hierarchy", { code: "ST01" }) as any;
    expect(reply.ancestors).toHaveLength(12);
    expect(reply.ancestors[11].code).toBe("A0");
    expect(reply.truncated).toBe(true);
  });

  it("caps siblings, children, terms and related entities at 12 and flags them", async () => {
    const many = (start: number, count: number) => Array.from({ length: count }, (_, index) => mms(start + index));
    const world13 = (extra: JsonRecord, parentChildren: string[] = [mms(1)]) => world(extra, {
      [mms(2)]: entityOf("11A", "Block", { parent: [mms(3)], child: parentChildren }),
      ...Object.fromEntries([...many(500, 14), ...many(600, 14)].map((uri, index) => [uri, entityOf(`Z${index}`, `Entity ${index}`)])),
      ...Object.fromEntries(Array.from({ length: 14 }, (_, index) => [fnd(700 + index), entityOf(`R${index}`, `Related ${index}`)])),
    });
    const siblings = await ask(world13({}, [mms(1), ...many(500, 13)]).who, "hierarchy", { code: "ST01" }) as any;
    expect(siblings.siblings).toHaveLength(12);
    expect(siblings.truncated).toBe(true);
    const children = await ask(world13({ child: many(600, 13) }).who, "hierarchy", { code: "ST01" }) as any;
    expect(children.children).toHaveLength(12);
    expect(children.truncated).toBe(true);
    const terms = await ask(world13({ indexTerm: Array.from({ length: 13 }, (_, index) => ({ label: title(`T${index}`) })) }).who, "hierarchy", { code: "ST01" }) as any;
    expect(terms.matching_terms).toHaveLength(12);
    expect(terms.truncated).toBe(true);
    const related = Array.from({ length: 13 }, (_, index) => fnd(700 + index));
    for (const field of ["relatedEntitiesInMaternalChapter", "relatedEntitiesInPerinatalChapter"]) {
      const reply = await ask(world13({ [field]: related }).who, "hierarchy", { code: "ST01" }) as any;
      expect(reply[field === "relatedEntitiesInMaternalChapter" ? "related_maternal" : "related_perinatal"]).toHaveLength(12);
      expect(reply.truncated).toBe(true);
    }
    // exactly 12 of each is not truncated
    const exact = await ask(world13({ child: many(600, 12), indexTerm: Array.from({ length: 12 }, (_, index) => ({ label: title(`T${index}`) })) }, [mms(1), ...many(500, 12)]).who, "hierarchy", { code: "ST01" }) as any;
    expect(exact.truncated).toBe(false);
  });

  it("ignores a related or term field WHO sends as something other than a list", async () => {
    const { who } = world({ indexTerm: "no", relatedEntitiesInMaternalChapter: "no", relatedEntitiesInPerinatalChapter: "no" });
    expect(await ask(who, "hierarchy", { code: "ST01" })).toMatchObject({ matching_terms: [], related_maternal: [], related_perinatal: [], truncated: false });
  });

  it("is unavailable for malformed children, and fails on an uncoded sibling or a missing related entity", async () => {
    await expect(ask(world({ child: "no" }).who, "hierarchy", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    const badSiblings = world({}, { [mms(2)]: entityOf("11A", "Block", { parent: [mms(3)], child: "no" }) });
    await expect(ask(badSiblings.who, "hierarchy", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    const uncoded = world({}, { [mms(7)]: entityOf("", "Uncoded leaf sibling") });
    await expect(ask(uncoded.who, "hierarchy", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    const lost = world({ relatedEntitiesInMaternalChapter: [fnd(50)] });
    await expectRefusal(ask(lost.who, "hierarchy", { code: "ST01" }), "CODE_NOT_FOUND");
    const foreign = world({ relatedEntitiesInMaternalChapter: [mms(50)] }, { [mms(50)]: entityOf("X", "x") });
    await expectRefusal(ask(foreign.who, "hierarchy", { code: "ST01" }), "INVALID_URI");
  });

  it("reads the related chapters before the sibling and child options", async () => {
    const { who, reads } = world({ relatedEntitiesInMaternalChapter: [fnd(50)] }, { [fnd(50)]: entityOf("JB64", "Maternal") });
    await ask(who, "hierarchy", { code: "ST01" });
    expect(reads.indexOf(fnd(50))).toBeLessThan(reads.indexOf(mms(7)));
    expect(reads.indexOf(fnd(50))).toBeLessThan(reads.indexOf(mms(5)));
  });
});

describe("related", () => {
  const related = (id: number, extra: JsonRecord = {}) => entityOf(`R${id}`, `Related ${id}`, { "@id": mms(id), ...extra });
  const world = (field: string, uris: string[], more: Entities, codeinfos: Record<string, JsonRecord | null> = {}) => fakeWho(
    { [mms(1)]: entityOf("ST01", "Stem", { [field]: uris }), ...more },
    { ST01: stemInfo("ST01", 1), ...codeinfos },
  );
  const M = "relatedEntitiesInMaternalChapter";

  it("returns the composite from the first related entity and the related entities with their children", async () => {
    const { who, reads } = world(M, [fnd(50), fnd(51)], {
      [mms(50)]: related(50, { child: [mms(60), mms(61)] }),
      [mms(60)]: related(60, { postcoordinationScale: [{ requiredPostcoordination: "true" }] }),
      [mms(61)]: entityOf("", "Uncoded child", { "@id": mms(61) }),
      [mms(51)]: related(51, { postcoordinationScale: [{ requiredPostcoordination: false }, "no"] }),
    });
    expect(await ask(who, "related", { code: "ST01", chapter: "maternal" })).toEqual({
      schema_version: 1,
      release: "2026-01",
      selected: { code: "ST01", title: "Stem", uri: mms(1) },
      chapter: "maternal",
      composite: { code: "R50/ST01", title: "Related 50 / Stem", uri: "" },
      terms: [
        { code: "R50", title: "Related 50", uri: mms(50), requires_postcoordination: false },
        { code: "R60", title: "Related 60", uri: mms(60), requires_postcoordination: true },
        { code: "R51", title: "Related 51", uri: mms(51), requires_postcoordination: false },
      ],
      truncated: false,
    });
    expect(reads).toContain(mms(50)); // the foundation id is read as its MMS entity
  });

  it("uses the perinatal list for perinatal, and answers an expression through its stem", async () => {
    const { who } = world("relatedEntitiesInPerinatalChapter", [fnd(50)], { [mms(50)]: related(50) }, { "ST01&XA00": { code: "ST01&XA00", stemCode: "ST01" } });
    expect(await ask(who, "related", { code: "ST01&XA00", chapter: "perinatal" })).toMatchObject({ chapter: "perinatal", terms: [{ code: "R50" }] });
    const maternal = await ask(who, "related", { code: "ST01", chapter: "maternal" }) as any;
    expect(maternal.terms).toEqual([]);
    expect(maternal.composite).toBeNull();
  });

  it("skips a related entity that has no coded form, takes the composite from the next one, and rethrows other failures", async () => {
    const { who } = world(M, [fnd(50), fnd(51)], { [mms(51)]: related(51) });
    const reply = await ask(who, "related", { code: "ST01", chapter: "maternal" }) as any;
    expect(reply.composite.code).toBe("R51/ST01");
    expect(reply.terms).toHaveLength(1);
    const broken = world(M, [fnd(50)], { [mms(50)]: 500 });
    await expect(ask(broken.who, "related", { code: "ST01", chapter: "maternal" })).rejects.toThrow(WhoUnavailableError);
    const badChild = world(M, [fnd(50)], { [mms(50)]: related(50, { child: [mms(60)] }) });
    await expectRefusal(ask(badChild.who, "related", { code: "ST01", chapter: "maternal" }), "CODE_NOT_FOUND");
  });

  it("has no composite when no related entity has a code and a title, and offers only coded, titled terms", async () => {
    for (const first of [entityOf("", "No code"), { code: "R50", title: title("") }, { code: 7, title: title("Seven") }]) {
      const { who } = world(M, [fnd(50)], { [mms(50)]: first });
      const reply = await ask(who, "related", { code: "ST01", chapter: "maternal" }) as any;
      expect(reply.composite).toBeNull();
      expect(reply.terms).toEqual([]);
    }
  });

  it("stops at 12 terms and flags truncation, including more than 12 related entities or children", async () => {
    const kids = Array.from({ length: 14 }, (_, index) => mms(100 + index));
    const many = world(M, [fnd(50)], {
      [mms(50)]: related(50, { child: kids }),
      ...Object.fromEntries(kids.map((uri, index) => [uri, related(100 + index)])),
    });
    const capped = await ask(many.who, "related", { code: "ST01", chapter: "maternal" }) as any;
    expect(capped.terms).toHaveLength(12);
    expect(capped.truncated).toBe(true);
    // 12 related entities, one term each: stops without reading a 13th; with 13 the flag is set up front
    const uris = Array.from({ length: 13 }, (_, index) => fnd(200 + index));
    const wide = world(M, uris, Object.fromEntries(uris.map((uri, index) => [mms(200 + index), related(200 + index)])));
    const reply = await ask(wide.who, "related", { code: "ST01", chapter: "maternal" }) as any;
    expect(reply.terms).toHaveLength(12);
    expect(reply.truncated).toBe(true);
    expect(wide.reads).not.toContain(mms(212));
    const fewKids = world(M, [fnd(50)], { [mms(50)]: related(50, { child: kids.slice(0, 3) }), ...Object.fromEntries(kids.slice(0, 3).map((uri, index) => [uri, related(100 + index)])) });
    expect((await ask(fewKids.who, "related", { code: "ST01", chapter: "maternal" }) as any).truncated).toBe(false);
    const twelveKids = world(M, [fnd(50)], { [mms(50)]: related(50, { child: kids.slice(0, 12) }), ...Object.fromEntries(kids.slice(0, 12).map((uri, index) => [uri, related(100 + index)])) });
    expect((await ask(twelveKids.who, "related", { code: "ST01", chapter: "maternal" }) as any).truncated).toBe(true); // 13 terms wanted, 12 kept
  });

  it("refuses a chapter that is not maternal or perinatal, and fails on malformed data", async () => {
    const { who } = world(M, [], {});
    for (const chapter of ["Maternal", "", 7, null, ["maternal"]]) {
      expect((await expectRefusal(ask(who, "related", { code: "ST01", chapter }), "INVALID_INPUT")).message).toBe("Choose a valid related chapter.");
    }
    await expect(ask(world(M, "no" as unknown as string[], {}).who, "related", { code: "ST01", chapter: "maternal" })).rejects.toThrow(WhoUnavailableError);
    const badKids = world(M, [fnd(50)], { [mms(50)]: related(50, { child: "no" }) });
    await expect(ask(badKids.who, "related", { code: "ST01", chapter: "maternal" })).rejects.toThrow(WhoUnavailableError);
    await expectRefusal(ask(world(M, [mms(50)], {}).who, "related", { code: "ST01", chapter: "maternal" }), "INVALID_URI");
    await expectRefusal(ask(world(M, [`${fnd(50)}/other`], {}).who, "related", { code: "ST01", chapter: "maternal" }), "INVALID_URI");
  });

  it("answers an expression without a stem as an invalid stem code", async () => {
    const { who } = world(M, [], {}, { "ST01&XA00": { code: "ST01&XA00" } });
    await expectRefusal(ask(who, "related", { code: "ST01&XA00", chapter: "maternal" }), "INVALID_INPUT");
    await expectRefusal(ask(who, "related", { code: "ST01&xa00", chapter: "maternal" }), "INVALID_INPUT");
    await expectRefusal(ask(who, "related", { code: "ST09&XA00", chapter: "maternal" }), "INVALID_INPUT"); // codeinfo unknown: no stem code
  });

  it("reads each related entity once through the client", async () => {
    const { who } = world(M, [fnd(50)], { [mms(50)]: related(50) });
    let ticks = 0;
    const counting: WhoEngineApi = { ...who, entity: async (uri) => { ticks += 1; return who.entity(uri); } };
    await ask(counting, "related", { code: "ST01", chapter: "maternal" });
    expect(ticks).toBe(2);
  });
});

describe("details", () => {
  const world = (extra: JsonRecord, more: Entities = {}, codeinfos: Record<string, JsonRecord | null> = {}) => fakeWho(
    { [mms(1)]: entityOf("ST01", "Stem", extra), ...more },
    { ST01: stemInfo("ST01", 1), ...codeinfos },
  );

  it("returns the text fields, the inclusions and the exclusions with their codes", async () => {
    const { who } = world(
      {
        definition: title("A <b>definition</b> &amp; more"),
        codingNote: title("Code also"),
        fullySpecifiedName: title("The full name"),
        inclusion: [{ label: title("Inc one") }, { label: title("") }, "no", { label: title("Inc two") }],
        exclusion: [
          { label: title("Excluded A"), linearizationReference: mms(30) },
          { label: title(""), linearizationReference: mms(31) },
          { label: title("No reference") },
          { label: title("Foundation only"), foundationReference: fnd(9) },
          "no",
        ],
      },
      { [mms(30)]: entityOf("EX01", "Entity A"), [mms(31)]: { title: title("Entity B, no code") } },
    );
    expect(await ask(who, "details", { code: "ST01" })).toEqual({
      schema_version: 1,
      release: "2026-01",
      selected: { code: "ST01", title: "Stem", uri: mms(1) },
      definition: "A definition & more",
      coding_note: "Code also",
      fully_specified_name: "The full name",
      inclusions: ["Inc one", "Inc two"],
      exclusions: [{ code: "EX01", title: "Excluded A" }, { code: "", title: "Entity B, no code" }],
      truncated: false,
    });
  });

  it("has empty text and lists for a code with none", async () => {
    expect(await ask(world({}).who, "details", { code: "ST01" })).toMatchObject({
      definition: "", coding_note: "", fully_specified_name: "", inclusions: [], exclusions: [], truncated: false,
    });
  });

  it("caps inclusions at 20 and exclusions at 12 and flags them", async () => {
    const exclusions = Array.from({ length: 13 }, (_, index) => ({ label: title(`Ex ${index}`), linearizationReference: mms(300 + index) }));
    const entities = Object.fromEntries(exclusions.map((_, index) => [mms(300 + index), entityOf(`E${index}`, `Entity ${index}`)]));
    const inclusion = (count: number) => Array.from({ length: count }, (_, index) => ({ label: title(`Inc ${index}`) }));
    const long = await ask(world({ exclusion: exclusions, inclusion: inclusion(21) }, entities).who, "details", { code: "ST01" }) as any;
    expect(long.exclusions).toHaveLength(12);
    expect(long.inclusions).toHaveLength(20);
    expect(long.truncated).toBe(true);
    expect((await ask(world({ inclusion: inclusion(21) }).who, "details", { code: "ST01" }) as any).truncated).toBe(true);
    expect((await ask(world({ exclusion: exclusions.slice(0, 12), inclusion: inclusion(20) }, entities).who, "details", { code: "ST01" }) as any).truncated).toBe(false);
  });

  it("answers an expression through its stem, and fails on malformed lists or a missing excluded entity", async () => {
    const via = world({}, {}, { "ST01&XA00": { code: "ST01&XA00", stemCode: "ST01" } });
    expect(await ask(via.who, "details", { code: "ST01&XA00" })).toMatchObject({ selected: { code: "ST01" } });
    await expect(ask(world({ exclusion: "no" }).who, "details", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    await expect(ask(world({ inclusion: "no" }).who, "details", { code: "ST01" })).rejects.toThrow(WhoUnavailableError);
    await expectRefusal(ask(world({ exclusion: [{ label: title("Gone"), linearizationReference: mms(30) }] }).who, "details", { code: "ST01" }), "CODE_NOT_FOUND");
    await expectRefusal(ask(world({}).who, "details", { code: "ST01/xb" }), "INVALID_INPUT");
  });
});

describe("answer: the route's body, the personal-data boundary and capacity", () => {
  const { who } = stemWorld({ postcoordinationScale: [] });
  const guidance = createGuidance(who);

  it("lists the five routes", () => {
    expect([...GUIDANCE_ENDPOINTS].sort()).toEqual(["details", "hierarchy", "postcoordination", "postcoordination-options", "related"]);
  });

  it("refuses a body that is not exactly schema_version 1 plus the route's fields", async () => {
    const bodies: unknown[] = [
      null, [], "text", 7, {}, { code: "ST01" }, { schema_version: 2, code: "ST01" }, { schema_version: "1", code: "ST01" },
      { schema_version: 1 }, { schema_version: 1, code: "ST01", extra: 1 }, { schema_version: 1, stem_code: "ST01" },
    ];
    for (const body of bodies) {
      const error = await expectRefusal(guidance.answer("postcoordination", body), "INVALID_INPUT");
      expect(error.message).toBe("The ICD-11 guidance request is invalid.");
    }
    await expectRefusal(guidance.answer("postcoordination-options", { schema_version: 1, stem_code: "ST01", axis_id: "a" }), "INVALID_INPUT");
    await expectRefusal(guidance.answer("related", { schema_version: 1, code: "ST01" }), "INVALID_INPUT");
    await expectRefusal(guidance.answer("hierarchy", { schema_version: 1, code: "ST01", chapter: "maternal" }), "INVALID_INPUT");
  });

  it("refuses personal data in any string before any read", async () => {
    const reads = jest.fn();
    const watching = createGuidance({ ...who, codeinfo: async (code) => { reads(code); return null; } });
    await expect(watching.answer("postcoordination", { schema_version: 1, code: "9876543210" })).rejects.toThrow(PiiBoundaryError);
    await expect(watching.answer("postcoordination-options", { schema_version: 1, stem_code: "ST01", axis_id: "a", parent_uri: "call 9876543210 now" })).rejects.toThrow(PiiBoundaryError);
    await expect(watching.answer("related", { schema_version: 1, code: "ST01", chapter: "1234 5678 9012" })).rejects.toThrow(PiiBoundaryError);
    // a non-string value is the port's concern, not the boundary's
    await expectRefusal(watching.answer("postcoordination", { schema_version: 1, code: 9876543210 }), "INVALID_INPUT");
    expect(reads).not.toHaveBeenCalled();
  });

  it("allows two requests at once, refuses a third with GUIDANCE_BUSY, and frees a slot when one ends", async () => {
    const release: Array<() => void> = [];
    const slow: WhoEngineApi = {
      ...who,
      codeinfo: (code) => new Promise((resolve) => { release.push(() => resolve(code === "ST01" ? stemInfo("ST01", 1) : null)); }),
    };
    const busy = createGuidance(slow);
    const first = busy.answer("details", { schema_version: 1, code: "ST01" });
    const second = busy.answer("hierarchy", { schema_version: 1, code: "ST01" });
    const third = await refusal(busy.answer("postcoordination", { schema_version: 1, code: "ST01" }));
    expect({ code: third.code, status: third.status, message: third.message }).toEqual({ code: "GUIDANCE_BUSY", status: 429, message: "WHO guidance is busy." });
    const settle = async () => {
      await new Promise((resolve) => setImmediate(resolve));
      release.splice(0).forEach((resolve) => resolve());
      await new Promise((resolve) => setImmediate(resolve));
    };
    await settle();
    await Promise.all([first, second]);
    // both ended: two more may run again
    const again = [busy.answer("postcoordination", { schema_version: 1, code: "ST01" }), busy.answer("details", { schema_version: 1, code: "ST01" })];
    await settle();
    await Promise.all(again);
    // a failed request also frees its slot
    const failing = createGuidance({ ...who, codeinfo: async () => { throw new WhoUnavailableError("down"); } });
    for (let index = 0; index < 4; index += 1) await expect(failing.answer("details", { schema_version: 1, code: "ST01" })).rejects.toThrow(WhoUnavailableError);
  });
});

describe("the editor's guidance route and requester", () => {
  /** An engine whose entities and codeinfo are plain maps (WHO's JSON), for the editor's own wiring. */
  function engineOf(codeinfo: Record<string, unknown>, entities: Record<string, unknown>): OfflineEngine {
    const answer = (found: unknown) => found === undefined ? { ok: false as const, error: "engine_status", status: 404, ms: 0 } : { ok: true as const, data: found, status: 200, ms: 0, nativeMs: 0 };
    return {
      available: async () => true,
      init: async () => ({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true }),
      warm: async () => ({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true }),
      updateWhoFiles: async () => ({ ok: true, ms: 0, copyMs: 0, initMs: 0, cached: true }),
      call: async () => ({ ok: false, error: "bad_op", ms: 0 }),
      search: async () => ({ ok: false, error: "engine_status", status: 500, ms: 0 }),
      codeinfo: async (code) => answer(codeinfo[code]),
      entity: async (id, options) => (entities.down ? { ok: false, error: "native_error", ms: 0 } : answer(entities[`${id}${options?.residual ? `/${options.residual}` : ""}`])),
      foundationEntity: async (id) => answer(entities[`f${id}`]),
      doris: async () => ({ ok: false, error: "engine_status", status: 500, ms: 0 }),
      codedit: async () => ({ ok: false, error: "engine_status", status: 500, ms: 0 }),
      onProgress: () => () => undefined,
    };
  }
  const store = { save: async () => undefined, get: async () => null };
  const engine = engineOf({ ST01: stemInfo("ST01", 1) }, { 1: entityOf("ST01", "Stem", { classKind: "category", postcoordinationScale: [] }) });
  const editor = createOfflineDorisEditor(engine, store);

  it("answers a route with the server's reply", async () => {
    expect(await editor.onGuidance("postcoordination", { schema_version: 1, code: "ST01" })).toMatchObject({
      schema_version: 1, stem: { code: "ST01", title: "Stem", uri: mms(1) }, axes: [],
    });
  });

  it("refuses with the server's ApiError: status, code, message and body", async () => {
    const failure = async (run: Promise<unknown>) => {
      const error = await run.then(() => null, (thrown: unknown) => thrown);
      expect(error).toBeInstanceOf(ApiError);
      return error as ApiError;
    };
    const invalid = await failure(editor.onGuidance("hierarchy", { code: "ST01" }));
    expect({ status: invalid.status, code: invalid.code, message: invalid.message, payload: invalid.payload }).toEqual({
      status: 422, code: "INVALID_INPUT", message: "The ICD-11 guidance request is invalid.",
      payload: { schema_version: 1, error: { code: "INVALID_INPUT", message: "The ICD-11 guidance request is invalid." } },
    });
    const unknown = await failure(editor.onGuidance("details", { schema_version: 1, code: "ZZ99" }));
    expect([unknown.status, unknown.code, unknown.message]).toEqual([422, "CODE_NOT_FOUND", "ICD-11 stem code was not found."]);
    const pii = await failure(editor.onGuidance("details", { schema_version: 1, code: "9876543210" }));
    expect(pii.status).toBe(422);
    expect(pii.code).toBe("INVALID_INPUT");
    expect(JSON.stringify(pii.payload)).toContain("pii_boundary");
    expect(JSON.stringify(pii.payload)).not.toContain("9876543210");
    const down = createOfflineDorisEditor(engineOf({ ST01: stemInfo("ST01", 1) }, { down: true }), store);
    const unavailable = await failure(down.onGuidance("details", { schema_version: 1, code: "ST01" }));
    expect([unavailable.status, unavailable.code, unavailable.message]).toEqual([503, "WHO_API_UNAVAILABLE", "WHO ICD-11 guidance is unavailable."]);
    const limit = await failure(createOfflineDorisEditor(engineOf({}, {}), store).onGuidance("postcoordination-options", { schema_version: 1, stem_code: "ST01", axis_id: "a", parent_uri: "x" }));
    expect(limit.code).toBe("CODE_NOT_FOUND");
  });

  it("passes on an error that is not the server's", async () => {
    const odd = { ...engine, codeinfo: async () => { throw new TypeError("boom"); } } as OfflineEngine;
    await expect(createOfflineDorisEditor(odd, store).onGuidance("details", { schema_version: 1, code: "ST01" })).rejects.toThrow(TypeError);
  });

  it("serves the picker's own client and parsers, and its error normalisation", async () => {
    const world = engineOf(
      { ST01: stemInfo("ST01", 1) },
      {
        1: entityOf("ST01", "Stem", {
          classKind: "category",
          postcoordinationScale: [scale("severity", [mms(10)])],
          parent: [mms(2)],
          child: [mms(5)],
          exclusion: [{ label: title("Excluded"), linearizationReference: mms(30) }],
          relatedEntitiesInMaternalChapter: [fnd(50)],
        }),
        2: entityOf("11A", "Block", { child: [mms(1)] }),
        5: entityOf("ST01.0", "Child"),
        10: entityOf("BB00", "Mild", { child: [mms(11)] }),
        11: entityOf("BB01", "Milder"),
        30: entityOf("EX01", "Entity"),
        50: entityOf("JB64", "Maternal", { "@id": mms(50) }),
        f50: entityOf("JB64", "Maternal"),
      },
    );
    const request = createGuidanceRequester(createOfflineDorisEditor(world, store), "draft-1", async () => undefined);
    const identity = { vaSid: "draft-1", mode: "coding" as const };
    const build = await dorisGuidance(request, identity, "postcoordination", { code: "ST01" }, parseDorisPostcoordination);
    expect(build.axes[0].options.map((item) => item.code)).toEqual(["BB00"]);
    expect(build.other_postcoordination).toEqual({ subtree_uris: [X_CHAPTER_URI] });
    const options = await dorisGuidance(request, identity, "postcoordination-options", { stem_code: "ST01", axis_id: "severity", parent_uri: mms(10) }, parseDorisOptions);
    expect(options.items.map((item) => item.code)).toEqual(["BB01"]);
    const hierarchy = await dorisGuidance(request, identity, "hierarchy", { code: "ST01" }, parseDorisHierarchy);
    expect(hierarchy.related_maternal.map((item) => item.code)).toEqual(["JB64"]);
    const maternal = await dorisGuidance(request, identity, "related", { code: "ST01", chapter: "maternal" }, parseDorisRelated);
    expect(maternal.composite?.code).toBe("JB64/ST01");
    const details = await dorisGuidance(request, identity, "details", { code: "ST01" }, parseDorisDetails);
    expect(details.exclusions).toEqual([{ code: "EX01", title: "Excluded" }]);
    // a refusal arrives as the server's: the picker's client unwraps `error.code` and `error.message`
    const refused = await dorisGuidance(request, identity, "details", { code: "ZZ99" }, parseDorisDetails).then(() => null, (thrown: unknown) => thrown);
    expect(refused).toBeInstanceOf(ApiError);
    expect([(refused as ApiError).status, (refused as ApiError).code, (refused as ApiError).message]).toEqual([422, "CODE_NOT_FOUND", "ICD-11 stem code was not found."]);
  });

  describe("requester", () => {
    const onGuidance = jest.fn(async (_endpoint: GuidanceEndpoint, body: unknown) => ({ echoed: body }));
    const allowed = jest.fn(async () => undefined);
    const request = createGuidanceRequester({ onGuidance }, "case 1/a", allowed);
    const post = (endpoint: string, sid = encodeURIComponent("case 1/a")) => `/api/v1/doris-clinical/${endpoint}/${sid}`;

    beforeEach(() => { onGuidance.mockClear(); allowed.mockClear(); });

    it.each(GUIDANCE_ENDPOINTS)("routes %s for the open case, after the allowed check", async (endpoint) => {
      await expect(request(post(endpoint), { method: "POST", json: { schema_version: 1, code: "ST01" } })).resolves.toEqual({ echoed: { schema_version: 1, code: "ST01" } });
      expect(onGuidance).toHaveBeenCalledWith(endpoint, { schema_version: 1, code: "ST01" });
      expect(allowed).toHaveBeenCalledTimes(1);
    });

    it("throws offline_server_unavailable for every other request, without calling anything", async () => {
      const others: Array<[string, { method?: "GET" | "POST"; json?: unknown } | undefined]> = [
        [post("hierarchy"), undefined],
        [post("hierarchy"), { method: "GET" }],
        [post("terms"), { method: "POST", json: {} }],
        [post("process"), { method: "POST", json: {} }],
        [post("hierarchy", "another-case"), { method: "POST", json: {} }],
        [post("hierarchy", "case%201%2Fa/extra"), { method: "POST", json: {} }],
        [`${post("hierarchy")}?x=1`, { method: "POST", json: {} }],
        ["/api/v1/other/hierarchy/x", { method: "POST", json: {} }],
        ["/api/v1/doris-clinical/postcoordination-optionsX/x", { method: "POST", json: {} }],
      ];
      for (const [path, init] of others) await expect(request(path, init)).rejects.toThrow("offline_server_unavailable");
      expect(onGuidance).not.toHaveBeenCalled();
      expect(allowed).not.toHaveBeenCalled();
    });

    it("does not answer when the case is no longer allowed", async () => {
      allowed.mockRejectedValueOnce(new Error("offline_case_access_revoked"));
      await expect(request(post("details"), { method: "POST", json: {} })).rejects.toThrow("offline_case_access_revoked");
      expect(onGuidance).not.toHaveBeenCalled();
    });
  });
});
