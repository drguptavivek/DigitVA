/** whoText.ts (the server's text helpers) and piiBoundary.ts (Rule 6 of vendor/who-icd11-api). */
import { assertNoPii, assertNoPiiInText, PiiBoundaryError } from "../src/workspace/piiBoundary";
import { codePointLength, isRecord, or, plain, plainText, truthy, unescapeHtml } from "../src/workspace/whoText";

describe("Python-like helpers", () => {
  it("isRecord accepts plain objects only", () => {
    expect([{}, { a: 1 }].every(isRecord)).toBe(true);
    expect([null, [], "x", 1, undefined].some(isRecord)).toBe(false);
  });

  it("truthy follows Python: empty list, dict, string, zero, null and false are falsy", () => {
    expect([[], {}, "", 0, null, undefined, false].map(truthy)).toEqual(new Array(7).fill(false));
    expect([[0], { a: null }, "x", 1, true].map(truthy)).toEqual(new Array(5).fill(true));
  });

  it("or falls through on a falsy first value", () => {
    expect(or([], "b")).toBe("b");
    expect(or("a", "b")).toBe("a");
  });

  it("codePointLength counts code points", () => {
    expect(codePointLength("abc")).toBe(3);
    expect(codePointLength("a😀")).toBe(2);
    expect(codePointLength("")).toBe(0);
  });
});

describe("unescapeHtml", () => {
  it("decodes named, decimal and hex entities in one pass", () => {
    expect(unescapeHtml("a &amp; b &lt;i&gt; &quot;x&quot; &#39;y&#39; &#x41; &nbsp;")).toBe("a & b <i> \"x\" 'y' A  ");
    expect(unescapeHtml("&amp;lt;")).toBe("&lt;");
  });

  it("leaves unknown names and invalid code points as they are", () => {
    expect(unescapeHtml("&bogus; &#0; &#xD800; &#1114112;")).toBe("&bogus; &#0; &#xD800; &#1114112;");
    expect(unescapeHtml("no entity & here")).toBe("no entity & here");
  });
});

describe("plain and plainText", () => {
  it("strips markup, decodes entities and trims", () => {
    expect(plain("  <em class='found'>Type 2</em> diabetes &amp; more ")).toBe("Type 2 diabetes & more");
    expect(plainText("<b>x</b> &lt;y&gt;")).toBe("x <y>");
  });

  it("reads {@value} then {label} of an object, and nothing else that is not a string", () => {
    expect(plain({ "@value": "Value", label: "Label" })).toBe("Value");
    expect(plain({ "@value": "", label: "Label" })).toBe("Label");
    expect(plain({})).toBe("");
    expect(plain({ "@value": 5 })).toBe("");
    expect(plain(["a"])).toBe("");
    expect(plain(null)).toBe("");
    expect(plainText({ label: "L" })).toBe("L");
    expect(plainText(7)).toBe("");
  });

  it("plain caps by code points; plainText joins a list of strings", () => {
    expect(plain("abcdef", 3)).toBe("abc");
    expect(plain("a😀b😀c", 4)).toBe("a😀b😀");
    expect(plain("x".repeat(300))).toHaveLength(200);
    expect(plainText(["a", 1, "b"])).toBe("a b");
  });
});

describe("piiBoundary: assertNoPii", () => {
  it.each([
    "name", "deceased_name", "informant_name", "respondent_name", "father_name", "mother_name", "spouse_name", "phone",
    "informant_phone", "respondent_phone", "mobile", "contact_number", "address", "house_address", "permanent_address",
    "aadhaar", "aadhaar_number", "aadhaar_last3", "abha", "abha_id", "abha_number", "national_id", "identifiers",
    "registration_number", "crs_number", "mccd_number", "certificate_number",
  ])("refuses the key %s without echoing its value", (key) => {
    const secret = "do-not-echo-this-value";
    let caught: unknown;
    try {
      assertNoPii({ Part1: [{ Conditions: [{ Text: "MI", [key]: secret }] }] }, "certificate");
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(PiiBoundaryError);
    const error = caught as PiiBoundaryError;
    expect(error.path).toBe(`certificate.Part1[0].Conditions[0].${key}`);
    expect(error.message).toContain("PII boundary violation");
    expect(error.message).not.toContain(secret);
  });

  it("matches keys trimmed and in any case, and refuses at the top level", () => {
    expect(() => assertNoPii({ " Informant_Phone ": "x" }, "")).toThrow(PiiBoundaryError);
    try {
      assertNoPii({ Aadhaar: 1 }, "");
    } catch (error) {
      expect((error as PiiBoundaryError).path).toBe("Aadhaar");
    }
  });

  it("refuses Aadhaar-like and phone numbers in any string, with their path", () => {
    expect(() => assertNoPii({ Text: "TB patient 2345 6789 0123" }, "certificate")).toThrow(/12-digit Aadhaar/);
    expect(() => assertNoPii({ Text: "id 2345-6789-0123." }, "certificate")).toThrow(PiiBoundaryError);
    expect(() => assertNoPii({ Text: "call 9876543210 now" }, "certificate")).toThrow(/10-digit phone/);
    expect(() => assertNoPii(["+91 9876543210"], "list")).toThrow(/list\[0\]/);
    expect(() => assertNoPiiInText("diabetes 9876543210", "query")).toThrow(PiiBoundaryError);
  });

  it("sees Indian-script and Arabic-Indic digits as digits", () => {
    expect(() => assertNoPiiInText("मरीज ९८७६५४३२१०", "query")).toThrow(/phone/);
    expect(() => assertNoPiiInText("٢٣٤٥ ٦٧٨٩ ٠١٢٣", "query")).toThrow(/Aadhaar/);
    expect(() => assertNoPiiInText("अ आ ई", "query")).not.toThrow();
  });

  it("lets clinical text, codes, short numbers and WHO URIs through", () => {
    expect(() => assertNoPii({
      ICDVersion: "ICD11",
      Part1: [{ Conditions: [{
        Text: "Pneumonia for 12 days, 98.6 F, 1B12.2&XA0G74",
        Code: "CA40.Z",
        LinearizationURI: "http://id.who.int/icd/release/11/2026-01/mms/1334938734/unspecified & http://id.who.int/icd/release/11/2026-01/mms/9876543210",
        Interval: "P12D",
      }] }],
      EstimatedAge: 65,
      Flag: true,
      Nothing: null,
    }, "certificate")).not.toThrow();
    // A phone number starts with 6 to 9; ten digits that start with 5 are neither a phone nor Aadhaar-like.
    expect(() => assertNoPiiInText("5678901234", "q")).not.toThrow();
  });
});
