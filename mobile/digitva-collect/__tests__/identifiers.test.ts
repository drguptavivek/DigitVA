import * as api from "../src/api";
import {
  checkIdentifier, cleanIdentifier, clearIdentifierTypeCache, identifierChanges, identifierFieldErrors, identifierIssues,
  identifiersToSend, identifierWarnings, isBadgeOnly, loadIdentifierTypes, typedCaret, putCaseIdentifiers, typedIdentifier, type IdentifierType,
} from "../src/identifiers";

const type = (over: Partial<IdentifierType> = {}): IdentifierType => ({
  code: "mccd", label: "MCCD number", min_length: 3, max_length: 8, char_type: null, pattern: null, example: null,
  required_at_report: false, sort_order: 1, ...over,
});

afterEach(() => { jest.restoreAllMocks(); clearIdentifierTypeCache(); });

describe("typing and cleaning", () => {
  it("upper-cases, normalises and drops leading space while typing", () => {
    expect(typedIdentifier("  ab/12 ")).toBe("AB/12 ");
    expect(typedIdentifier("mccd")).toHaveLength(4);
    expect(typedIdentifier("１２３")).toBe("123");
  });
  it("places the caret from the old selection and the length delta", () => {
    // typing "x" at 3 in "MCCD12"
    expect(typedCaret("MCCD12", { start: 3, end: 3 }, "MCCxD12")).toEqual({ value: "MCCXD12", caret: 4 });
    // nothing changed: leave the caret to the platform
    expect(typedCaret("MCC", { start: 3, end: 3 }, "MCCD")).toEqual({ value: "MCCD" });
    // "ß" becomes "SS": one char typed, two shown
    expect(typedCaret("AB", { start: 1, end: 1 }, "AßB")).toEqual({ value: "ASSB", caret: 3 });
    // a leading space typed at the start goes, caret stays at 0
    expect(typedCaret("AB", { start: 0, end: 0 }, " AB")).toEqual({ value: "AB", caret: 0 });
    // a paste over a selection
    expect(typedCaret("ABCDE", { start: 1, end: 3 }, "Axyz DE")).toEqual({ value: "AXYZ DE", caret: 5 });
  });
  it("accepts fullwidth digits typed on an IME", () => {
    expect(cleanIdentifier("１２３４５６")).toBe("123456");
    expect(checkIdentifier(type({ char_type: "digits", min_length: 6, max_length: 6 }), "１２３４５６")).toBeUndefined();
    expect(identifiersToSend({ mccd: "１２３４５６" })).toEqual({ mccd: "123456" });
  });
  it("trims and collapses space when sending", () => {
    expect(cleanIdentifier("  ab   12 ")).toBe("AB 12");
    expect(cleanIdentifier(null)).toBe("");
  });
});

describe("checkIdentifier", () => {
  it("checks length first", () => {
    expect(checkIdentifier(type(), "ab")).toBe("length");
    expect(checkIdentifier(type(), "abcdefghi")).toBe("length");
    expect(checkIdentifier(type(), "abc")).toBeUndefined();
  });
  it.each([
    ["digits", "123", "12a"],
    ["letters", "ABC", "AB1"],
    ["letters_digits", "AB1", "AB-"],
    ["letters_digits_hyphen_slash", "A-1/B", "A_1"],
  ] as const)("char type %s", (char_type, good, bad) => {
    expect(checkIdentifier(type({ char_type }), good)).toBeUndefined();
    expect(checkIdentifier(type({ char_type }), bad)).toBe("char_type");
  });
  it("matches the whole value against the pattern, on the capitalised text", () => {
    const t = type({ max_length: 20, pattern: "MCCD/[0-9]{4}/[0-9]+" });
    expect(checkIdentifier(t, "mccd/2026/12")).toBeUndefined();
    expect(checkIdentifier(t, "x mccd/2026/12")).toBe("pattern");
    expect(checkIdentifier(t, "MCCD/2026/12/9Z")).toBe("pattern");
  });
  it("never blocks on a pattern that does not compile", () => {
    expect(checkIdentifier(type({ pattern: "(unclosed" }), "abcd")).toBeUndefined();
  });
  it("treats an empty value as nothing to check", () => {
    expect(checkIdentifier(type(), "   ")).toBeUndefined();
  });
});

describe("identifierIssues", () => {
  it("requires required types only when asked", () => {
    const types = [type({ required_at_report: true })];
    expect(identifierIssues(types, {})).toEqual({});
    expect(identifierIssues(types, {}, true)).toEqual({ mccd: "required" });
    expect(identifierIssues(types, { mccd: "ab" }, true)).toEqual({ mccd: "length" });
  });
});

describe("isBadgeOnly", () => {
  it("is judged by the list: one undecryptable entry among values is not badge-only", () => {
    expect(isBadgeOnly([{ code: "a", label: "A", present: true }, { code: "b", label: "B", present: false }])).toBe(true);
    expect(isBadgeOnly([{ code: "a", label: "A", value: "X1" }, { code: "b", label: "B", present: true }])).toBe(false);
    expect(isBadgeOnly([{ code: "a", label: "A", value: null }])).toBe(false);
    expect(isBadgeOnly([])).toBe(false);
    expect(isBadgeOnly(undefined)).toBe(false);
  });
});

describe("payload helpers", () => {
  it("sends only non-empty cleaned values on a registration", () => {
    expect(identifiersToSend({ a: " x1 ", b: "  ", c: undefined })).toEqual({ a: "X1" });
    expect(identifiersToSend({ b: "" })).toBeUndefined();
    expect(identifiersToSend(undefined)).toBeUndefined();
  });
  it("sends only changed codes on a correction and null to clear", () => {
    expect(identifierChanges({ a: "X1", b: "Y2" }, { a: "x1", b: "", c: "z3" })).toEqual({ b: null, c: "Z3" });
    expect(identifierChanges({ a: "X1" }, { a: "X1" })).toEqual({});
  });
  it("reads field errors and duplicate warnings from replies", () => {
    const error = new api.ApiError(422, "invalid_death", undefined, undefined, { error: "bad", fields: ["identifiers.mccd", "deceased_name"] });
    expect(identifierFieldErrors(error)).toEqual({ mccd: "bad" });
    expect(identifierFieldErrors(new Error("x"))).toEqual({});
    expect(identifierWarnings({ warnings: [{ code: "identifier_in_use", field: "identifiers.mccd", message: "m" }, { code: "other", field: "x", message: "n" }] })).toEqual({ mccd: "m" });
    expect(identifierWarnings({})).toEqual({});
  });
});

describe("calls", () => {
  it("PUTs the any-time write through the shared requester with the CSRF token and if_updated_at", async () => {
    const request = jest.spyOn(api, "requestClientJson").mockResolvedValue({ case: {} } as never);
    const csrf = { header: "X-CSRFToken", token: "tok" };
    await putCaseIdentifiers("/api/v1/intake/cases/", "d 1", { mccd: "A1", old: null }, "2026-10-21T00:00:00Z", csrf);
    expect(request).toHaveBeenCalledWith("/api/v1/intake/cases/d%201/identifiers", {
      method: "PUT",
      json: { identifiers: { mccd: "A1", old: null }, if_updated_at: "2026-10-21T00:00:00Z" },
      csrf,
    });
  });

  it("carries the CSRF header on the wire for the PUT", async () => {
    const fetchMock = jest.fn(async () => new Response(JSON.stringify({ case: {} }), { status: 200, headers: { "Content-Type": "application/json" } }));
    const original = globalThis.fetch;
    globalThis.fetch = fetchMock as unknown as typeof fetch;
    try {
      await putCaseIdentifiers("/api/v1/intake/cases", "d1", { mccd: "A1" }, undefined, { header: "X-CSRFToken", token: "tok" });
      const init = (fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1];
      expect(init.method).toBe("PUT");
      expect((init.headers as Record<string, string>)["X-CSRFToken"]).toBe("tok");
      expect(JSON.parse(init.body as string)).toEqual({ identifiers: { mccd: "A1" } });
    } finally {
      globalThis.fetch = original;
    }
  });

  it("caches types per project, rejects on failure and retries after a failure", async () => {
    const types = [type()];
    const request = jest.spyOn(api, "requestClientJson").mockResolvedValueOnce({ identifier_types: types } as never);
    expect(await loadIdentifierTypes("P1")).toEqual(types);
    expect(await loadIdentifierTypes("P1")).toEqual(types);
    expect(request).toHaveBeenCalledTimes(1);
    expect(request.mock.calls[0][0]).toBe("/api/v1/intake/identifier-types?project_id=P1");
    request.mockRejectedValueOnce(new Error("offline"));
    await expect(loadIdentifierTypes("P2")).rejects.toThrow("offline");
    request.mockResolvedValueOnce({ identifier_types: types } as never);
    expect(await loadIdentifierTypes("P2")).toEqual(types);
  });
});
