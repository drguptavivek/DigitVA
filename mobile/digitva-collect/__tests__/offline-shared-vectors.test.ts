import { readFileSync } from "fs";
import { join } from "path";

import { reduceNationalIdData } from "@drguptavivek/who-2022-va";

import { checkIdentifier, cleanIdentifier, PII_FIELDS_FLOOR, type IdentifierType } from "../src/identifiers";
import { normalisePhone } from "../src/phoneFormat";

// The shared vectors (offline-api-contract.md 14). The server's Python tests and the station's Rust
// tests read the same files; the Python functions are the authority.
function fixture<T>(name: string): T {
  return JSON.parse(readFileSync(join(__dirname, "../../../tests/fixtures", name), "utf8")) as T;
}

type Case<E> = { input: string; expected: E };

describe("shared phone vectors", () => {
  const { cases } = fixture<{ cases: Case<string | null>[] }>("phone_vectors.json");

  it("has cases", () => expect(cases.length).toBeGreaterThan(0));
  it.each(cases.map((c) => [JSON.stringify(c.input), c] as const))("%s", (_name, c) => {
    expect(normalisePhone(c.input)).toBe(c.expected);
  });
});

describe("shared identifier vectors", () => {
  const data = fixture<{
    rules: Record<string, Omit<IdentifierType, "required_at_report" | "sort_order">>;
    normalise: Case<string | null>[];
    validate: Array<Case<{ value: string | null } | { error: string }> & { rule: string }>;
  }>("identifier_vectors.json");

  it("has cases", () => {
    expect(data.normalise.length).toBeGreaterThan(0);
    expect(data.validate.length).toBeGreaterThan(0);
  });
  it.each(data.normalise.map((c) => [JSON.stringify(c.input), c] as const))("normalises %s", (_name, c) => {
    expect(cleanIdentifier(c.input) || null).toBe(c.expected);
  });
  it.each(data.validate.map((c) => [`${c.rule} ${JSON.stringify(c.input)}`, c] as const))("validates %s", (_name, c) => {
    const type: IdentifierType = { ...data.rules[c.rule], required_at_report: false, sort_order: 0 };
    const value = cleanIdentifier(c.input) || null;
    const broken = value === null ? undefined : checkIdentifier(type, value);
    expect(broken ? { error: broken } : { value }).toEqual(c.expected);
  });
});

describe("shared national ID (Id10073) vectors", () => {
  const { cases } = fixture<{ cases: Case<string | null>[] }>("national_id_vectors.json");

  it("has cases", () => expect(cases.length).toBeGreaterThan(0));
  it.each(cases.map((c) => [JSON.stringify(c.input), c] as const))("%s", (_name, c) => {
    // A null reduction means "not answered": the answer is kept as given.
    expect(reduceNationalIdData({ Id10073: c.input }).Id10073).toBe(c.expected ?? c.input);
  });
});

describe("shared PII_FIELDS floor", () => {
  it("is the server's PII_FIELDS", () => {
    const { fields } = fixture<{ fields: string[] }>("pii_fields_floor.json");
    expect(fields).toContain("Id10073");
    expect([...PII_FIELDS_FLOOR].sort()).toEqual([...fields].sort());
  });
});
