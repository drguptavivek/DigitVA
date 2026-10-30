import { parseDorisDetails, parseDorisPostcoordination, type DorisAxis, type DorisOption } from "../src/workspace/doris/guidance";
import { parseDorisTerms } from "../src/workspace/contracts";
import { Notice, PickerError, errorMessage } from "../src/workspace/doris/picker/transport";
import { buildExpression, causingUnknownApplies, isComplete, isExtension, isMandatory, looksCode, requiredSatisfied, splitExpression, toggleOption } from "../src/workspace/doris/picker/expression";

const option = (code: string, block = ""): DorisOption => ({ code, title: `T ${code}`, uri: `u/${code}`, has_children: false, ...(block ? { block_uri: block } : {}) });
const axis = (id: string, policy: DorisAxis["allow_multiple_values"], required = false): DorisAxis => ({ id, label: id, required, allow_multiple_values: policy, options: [], subtree_uris: [], truncated: false });

describe("code and expression tests", () => {
  it("tells codes from text", () => {
    expect(looksCode("CA40")).toBe(true);
    expect(looksCode("CA40.1")).toBe(true);
    expect(looksCode("pneumonia")).toBe(false);
    expect(looksCode("type 2")).toBe(false);
    expect(isComplete("BD54/MC85")).toBe(true);
    expect(isComplete("BD54&XK9J")).toBe(true);
    expect(isComplete("BD54")).toBe(false);
    expect(isExtension("XK9J")).toBe(true);
    expect(isExtension("xk9j")).toBe(true);
    expect(isExtension("MC85")).toBe(false);
    expect(isMandatory({ code: "a", title: "", uri: "", postcoordination_availability: 2 })).toBe(true);
    expect(isMandatory({ code: "a", title: "", uri: "", postcoordination_availability: 1 })).toBe(false);
    expect(splitExpression("BD54&XK9J/MC85")).toEqual({ stem: "BD54", parts: ["XK9J", "MC85"] });
    expect(splitExpression("CA40")).toEqual({ stem: "CA40", parts: [] });
  });
});

describe("toggleOption", () => {
  it("AllowAlways toggles each value", () => {
    const a = axis("a", "AllowAlways");
    const one = toggleOption(a, [], option("A"));
    expect(one.map((o) => o.code)).toEqual(["A"]);
    const two = toggleOption(a, one, option("B"));
    expect(two.map((o) => o.code)).toEqual(["A", "B"]);
    expect(toggleOption(a, two, option("A")).map((o) => o.code)).toEqual(["B"]);
  });

  it("AllowedExceptFromSameBlock replaces within a block and keeps other blocks", () => {
    const a = axis("a", "AllowedExceptFromSameBlock");
    const first = toggleOption(a, [], option("A", "b1"));
    const second = toggleOption(a, first, option("B", "b2"));
    expect(second.map((o) => o.code)).toEqual(["A", "B"]);
    expect(toggleOption(a, second, option("C", "b1")).map((o) => o.code)).toEqual(["C", "B"]);
    expect(toggleOption(a, second, option("A", "b1")).map((o) => o.code)).toEqual(["B"]);
    // Without a block uri two values never replace each other.
    expect(toggleOption(a, [option("D")], option("E")).map((o) => o.code)).toEqual(["D", "E"]);
  });

  it("NotAllowed keeps one value and does not toggle it off", () => {
    const a = axis("a", "NotAllowed");
    expect(toggleOption(a, [option("A")], option("B")).map((o) => o.code)).toEqual(["B"]);
    expect(toggleOption(a, [option("A")], option("A")).map((o) => o.code)).toEqual(["A"]);
  });
});

describe("required axes and the expression", () => {
  const causing = axis("hasCausingCondition", "NotAllowed", true);
  const other = axis("other", "AllowAlways", true);
  const optional = axis("opt", "AllowAlways");
  const stem = { code: "BD54", title: "Stem", uri: "u/BD54" };

  it("a required axis needs a value, or causing-condition unknown for that axis only", () => {
    expect(requiredSatisfied([optional], {}, false)).toBe(true);
    expect(requiredSatisfied([causing], {}, false)).toBe(false);
    expect(requiredSatisfied([causing], { hasCausingCondition: [option("5A11")] }, false)).toBe(true);
    expect(requiredSatisfied([causing], {}, true)).toBe(true);
    expect(requiredSatisfied([other], {}, true)).toBe(false);
    expect(causingUnknownApplies([causing], {}, true)).toBe(true);
    expect(causingUnknownApplies([causing], { hasCausingCondition: [option("5A11")] }, true)).toBe(false);
    expect(causingUnknownApplies([causing], {}, false)).toBe(false);
    expect(causingUnknownApplies([other], {}, true)).toBe(false);
  });

  it("joins X extensions with & first, then / stems, in axis order, with the other pick last of the extensions", () => {
    const axes = [axis("a", "AllowAlways"), axis("b", "AllowAlways")];
    const built = buildExpression(stem, axes, { a: [option("5A11"), option("XA1")], b: [option("XB2"), option("MC85")] }, option("XO9"), false);
    expect(built.code).toBe("BD54&XA1&XB2&XO9/5A11/MC85");
    expect(built.uri).toBe("u/BD54 & u/XA1 & u/XB2 & u/XO9 / u/5A11 / u/MC85");
    expect(built.title).toBe("Stem; T XA1; T XB2; T XO9; T 5A11; T MC85");
    expect(built.causingUnknown).toBeUndefined();
  });

  it("is the bare stem with nothing chosen, and flags an unknown causing condition", () => {
    expect(buildExpression(stem, [optional], {}, null, false)).toEqual({ code: "BD54", uri: "u/BD54", title: "Stem" });
    expect(buildExpression({ ...stem, title: "" }, [causing], {}, null, true)).toMatchObject({ code: "BD54", title: "", causingUnknown: true });
  });
});

describe("guidance parsers added for the picker", () => {
  it("keeps the WHO axis instruction when present", () => {
    const base = { schema_version: 1, stem: { code: "BD54", title: "Stem", uri: "u" }, other_postcoordination: null, truncated: false };
    const axisReply = (instruction?: unknown) => ({ ...base, axes: [{ id: "a", label: "A", ...(instruction === undefined ? {} : { instruction }), required: false, allow_multiple_values: "AllowAlways", options: [], subtree_uris: [], truncated: false }] });
    expect(parseDorisPostcoordination(axisReply("code also")).axes[0].instruction).toBe("code also");
    expect(parseDorisPostcoordination(axisReply()).axes[0]).not.toHaveProperty("instruction");
    expect(parseDorisPostcoordination(axisReply("")).axes[0]).not.toHaveProperty("instruction");
  });

  it("parses details and tolerates absent fields", () => {
    expect(parseDorisDetails({ schema_version: 1, coding_note: "n", definition: "d", fully_specified_name: "f", inclusions: ["i", 4], exclusions: [{ code: "X1", title: "x" }, { title: "y" }], truncated: true })).toEqual({
      coding_note: "n", definition: "d", fully_specified_name: "f", inclusions: ["i"], exclusions: [{ code: "X1", title: "x" }, { code: "", title: "y" }], truncated: true,
    });
    expect(parseDorisDetails({ schema_version: 1 })).toEqual({ coding_note: "", definition: "", fully_specified_name: "", inclusions: [], exclusions: [], truncated: false });
    expect(() => parseDorisDetails({ schema_version: 2 })).toThrow("Invalid DORIS details response.");
    expect(() => parseDorisDetails("x")).toThrow("details");
    expect(() => parseDorisDetails({ schema_version: 1, exclusions: [{ code: "A" }] })).toThrow("exclusions[0].title");
  });
});

describe("errorMessage", () => {
  it("shows a known DORIS code as our own fixed line and everything else as the generic one", () => {
    expect(errorMessage(new PickerError("raw server text", "CODE_NOT_FOUND", 422))).toBe("Select a valid ICD-11 code.");
    expect(errorMessage(new PickerError("raw server text", "WHO_API_UNAVAILABLE", 503))).toBe("The WHO ICD-11 service is unavailable. Try again shortly.");
    expect(errorMessage(new PickerError("raw server text", "INVALID_INPUT", 422))).not.toContain("raw server text");
    expect(errorMessage(new PickerError("raw server text", "INVALID_SELECTION", 422))).toBe("The selected code does not match its WHO URI.");
    expect(errorMessage(new PickerError("raw server text", "NOT_AVAILABLE", 409))).toBe("This case is not available here.");
    for (const raw of [new PickerError("HTTP 502 code", "request_failed", 502), new PickerError("x", "constructor", 0), new Error("Invalid DORIS response: axes[0].id"), new Error("offline_server_unavailable"), new Error(""), "boom"]) {
      expect(errorMessage(raw)).toBe("The request could not be completed.");
    }
  });

  it("shows the picker's own notices as written", () => {
    expect(errorMessage(new Notice("WHO did not return CA40."))).toBe("WHO did not return CA40.");
  });
});

describe("parseDorisTerms optional age tag", () => {
  const term = { code: "CA40", title: "Pneumonia", uri: "u", release: "r", matching_text: "p", postcoordination: false, postcoordination_availability: 0, related_maternal: false, related_perinatal: false, has_coding_note: false };
  const parse = (extra: Record<string, unknown>) => parseDorisTerms({ schema_version: 1, items: [{ ...term, ...extra }], truncated: false, next_cursor: null }).items[0];

  it("leaves the term as it was when the reply carries no age fields or wrong types", () => {
    expect(parse({})).toEqual(term);
    expect(parse({ age_restricted: "yes", restriction_note: 5 })).toEqual(term);
    expect(parse({ age_restricted: false, restriction_note: "" })).toEqual(term);
  });

  it("keeps the age tag and its note when the reply carries them", () => {
    expect(parse({ age_restricted: true, restriction_note: "Under 5 only." })).toEqual({ ...term, age_restricted: true, restriction_note: "Under 5 only." });
    expect(parse({ age_restricted: true })).toEqual({ ...term, age_restricted: true });
  });
});
