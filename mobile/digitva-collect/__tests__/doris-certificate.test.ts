/** The certificate rules of app/services/doris_certificate.py, ported in dorisCertificate.ts: same checks, paths and words. */
import {
  canonicalJson, dropInapplicableSections, DorisCertificateError, expectedExpressionUri, normalizeCertificate,
  verifyCertificateCodes, whoSafeCertificate,
} from "../src/workspace/dorisCertificate";
import type { WhoEngineApi } from "../src/workspace/whoEngineApi";

type Json = Record<string, any>;
const base = (): Json => ({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Sepsis" }] }] });
const withCert = (extra: Json): Json => ({ ...base(), ...extra });

function refusal(certificate: unknown): { path: string; message: string } {
  try {
    normalizeCertificate(certificate);
  } catch (error) {
    expect(error).toBeInstanceOf(DorisCertificateError);
    const fields = (error as DorisCertificateError).fields;
    expect(fields).toHaveLength(1);
    return fields[0];
  }
  throw new Error("expected a refusal");
}

describe("normalizeCertificate: shape", () => {
  it("returns a normalised copy with the release, leaving the input alone", () => {
    const input = withCert({ Part2: { Conditions: [{ Text: " Diabetes ", Interval: " P2Y " }] } });
    const before = JSON.stringify(input);
    const result = normalizeCertificate(input);
    expect(JSON.stringify(input)).toBe(before);
    expect(result).toEqual({
      ICDVersion: "ICD11", ICDMinorVersion: "2026-01",
      Part1: [{ Conditions: [{ Text: "Sepsis" }] }],
      Part2: { Conditions: [{ Text: "Diabetes", Interval: "P2Y" }] },
    });
  });

  it("refuses what is not a certificate object, an unsupported key, another version or release", () => {
    expect(refusal(null)).toEqual({ path: "certificate", message: "Must be an object." });
    expect(refusal([])).toEqual({ path: "certificate", message: "Must be an object." });
    expect(refusal(withCert({ Extra: 1 }))).toEqual({ path: "certificate", message: "Contains unsupported fields." });
    expect(refusal({ ...base(), ICDVersion: "ICD10" })).toEqual({ path: "certificate.ICDVersion", message: "Must be ICD11." });
    expect(refusal(withCert({ ICDMinorVersion: "2025-01" }))).toEqual({ path: "certificate.ICDMinorVersion", message: "Must match the configured release." });
    expect(() => normalizeCertificate(withCert({ ICDMinorVersion: "2026-01" }))).not.toThrow();
    expect(() => normalizeCertificate(withCert({ ICDMinorVersion: null }))).not.toThrow();
  });

  it("refuses Part I that is missing, empty, too long or malformed", () => {
    const part1 = { path: "certificate.Part1", message: "Enter at least one Part I line." };
    expect(refusal({ ICDVersion: "ICD11" })).toEqual(part1);
    expect(refusal({ ICDVersion: "ICD11", Part1: [] })).toEqual(part1);
    expect(refusal({ ICDVersion: "ICD11", Part1: "x" })).toEqual(part1);
    const line = { Conditions: [{ Text: "a" }] };
    expect(refusal({ ICDVersion: "ICD11", Part1: Array(6).fill(line) })).toEqual({ path: "certificate.Part1", message: "Part I may contain at most 5 lines." });
    expect(refusal({ ICDVersion: "ICD11", Part1: [null] })).toEqual({ path: "certificate.Part1[0]", message: "Must contain only Conditions." });
    expect(refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a" }], Extra: 1 }] })).toEqual({ path: "certificate.Part1[0]", message: "Must contain only Conditions." });
    expect(refusal({ ICDVersion: "ICD11", Part1: [{ Other: [] }] })).toEqual({ path: "certificate.Part1[0]", message: "Must contain only Conditions." });
  });

  it("refuses Part II that is not {Conditions: list}, and accepts none, null and an empty list", () => {
    expect(refusal(withCert({ Part2: [] }))).toEqual({ path: "certificate.Part2", message: "Must contain only Conditions." });
    expect(refusal(withCert({ Part2: { Conditions: [], Extra: 1 } }))).toEqual({ path: "certificate.Part2", message: "Must contain only Conditions." });
    expect(refusal(withCert({ Part2: { Other: 1 } }))).toEqual({ path: "certificate.Part2", message: "Must contain only Conditions." });
    expect(refusal(withCert({ Part2: { Conditions: "x" } }))).toEqual({ path: "certificate.Part2.Conditions", message: "Must be a list." });
    expect(normalizeCertificate(withCert({ Part2: { Conditions: [] } })).Part2).toEqual({ Conditions: [] });
    expect(normalizeCertificate(withCert({ Part2: null })).Part2).toBeNull();
    expect(normalizeCertificate(base())).not.toHaveProperty("Part2");
  });

  it("limits the conditions to 20 and the canonical JSON to 32 KiB (counted in UTF-8 bytes)", () => {
    const line = (count: number) => ({ Conditions: Array.from({ length: count }, () => ({ Text: "a" })) });
    expect(refusal({ ICDVersion: "ICD11", Part1: [line(7), line(7), line(7)] })).toEqual({ path: "certificate", message: "A certificate may contain at most 20 conditions." });
    expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [line(7), line(7), line(6)] })).not.toThrow();
    const coded = (uri: string, text = "a") => ({ Conditions: [{ Text: text, Code: "CA40.Z", LinearizationURI: uri }] });
    const heavy = {
      ICDVersion: "ICD11",
      Part1: Array.from({ length: 5 }, () => coded("x".repeat(2048))),
      // 1-, 2-, 3- and 4-byte characters; the second block is 8 x 2000 four-byte characters.
      Part2: { Conditions: Array.from({ length: 8 }, () => ({ Text: "aé€😀", Code: "CA40.Z", LinearizationURI: "😀".repeat(2000) })) },
    };
    expect(refusal(heavy)).toEqual({ path: "certificate", message: "The certificate is too large." });
  });
});

describe("normalizeCertificate: conditions", () => {
  const condition = (value: unknown) => refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: [value] }] });
  const at = "certificate.Part1[0].Conditions[0]";

  it("requires conditions as a non-empty list of at most 8", () => {
    expect(refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: [] }] })).toEqual({ path: "certificate.Part1[0].Conditions", message: "Enter at least one condition." });
    expect(refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: "x" }] })).toEqual({ path: "certificate.Part1[0].Conditions", message: "Enter at least one condition." });
    expect(refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: Array(9).fill({ Text: "a" }) }] })).toEqual({ path: "certificate.Part1[0].Conditions", message: "A line may contain at most 8 conditions." });
  });

  it("checks each condition's shape and text", () => {
    expect(condition("x")).toEqual({ path: at, message: "Must be an object." });
    expect(condition({ Text: "a", Extra: 1 })).toEqual({ path: at, message: "Contains unsupported fields." });
    expect(condition({})).toEqual({ path: `${at}.Text`, message: "Enter condition text." });
    expect(condition({ Text: "   " })).toEqual({ path: `${at}.Text`, message: "Enter condition text." });
    expect(condition({ Text: 5 })).toEqual({ path: `${at}.Text`, message: "Enter condition text." });
    expect(condition({ Text: "a".repeat(501) })).toEqual({ path: `${at}.Text`, message: "Must be 500 characters or fewer." });
    expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "😀".repeat(500) }] }] })).not.toThrow();
  });

  it("needs Code and LinearizationURI together, both valid, and strips them", () => {
    expect(condition({ Text: "a", Code: "CA40.Z" })).toEqual({ path: at, message: "Code and LinearizationURI must be supplied together." });
    expect(condition({ Text: "a", LinearizationURI: "http://x" })).toEqual({ path: at, message: "Code and LinearizationURI must be supplied together." });
    for (const code of [5, "  ", "A".repeat(129)]) {
      expect(condition({ Text: "a", Code: code, LinearizationURI: "http://x" })).toEqual({ path: `${at}.Code`, message: "Must be a valid ICD-11 expression." });
    }
    for (const uri of [5, "  ", "u".repeat(2049)]) {
      expect(condition({ Text: "a", Code: "CA40.Z", LinearizationURI: uri })).toEqual({ path: `${at}.LinearizationURI`, message: "Must be a valid WHO URI." });
    }
    const result = normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", Code: " CA40.Z ", LinearizationURI: " http://x ", FoundationURI: " f ", Code2: undefined }] }] });
    expect((result.Part1 as Json[])[0].Conditions[0]).toEqual({ Text: "a", Code: "CA40.Z", LinearizationURI: "http://x", FoundationURI: "f" });
    const explicitNull = normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", Code: null, LinearizationURI: null, FoundationURI: null, Interval: null }] }] });
    expect((explicitNull.Part1 as Json[])[0].Conditions[0]).toEqual({ Text: "a", Code: null, LinearizationURI: null, FoundationURI: null, Interval: null });
  });

  it("checks FoundationURI and Interval, and one interval per line", () => {
    expect(condition({ Text: "a", FoundationURI: 5 })).toEqual({ path: `${at}.FoundationURI`, message: "Must be text." });
    expect(condition({ Text: "a", Interval: 5 })).toEqual({ path: `${at}.Interval`, message: "Must be text." });
    expect(condition({ Text: "a", Interval: "two days" })).toEqual({ path: `${at}.Interval`, message: "Must be a valid ISO 8601 duration." });
    expect(condition({ Text: "a", Interval: "P" + "1".repeat(70) + "D" })).toEqual({ path: `${at}.Interval`, message: "Must be a valid ISO 8601 duration." });
    expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", Interval: "" }] }] })).not.toThrow();
    for (const interval of ["P", "P2Y", "P1Y2M3D", "PT5H", "P1DT2H30M", "P2W", "P1.5D", "PT0.5S"]) {
      expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", Interval: interval }] }] })).not.toThrow();
    }
    const mixed = (first: Json, second: Json) => refusal({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", ...first }, { Text: "b", ...second }] }] });
    const same = { path: "certificate.Part1[0].Conditions", message: "All conditions on a line must use the same interval." };
    expect(mixed({ Interval: "P1D" }, { Interval: "P2D" })).toEqual(same);
    expect(mixed({ Interval: "P1D" }, {})).toEqual(same);
    expect(mixed({ Interval: "P1D" }, { Interval: "" })).toEqual(same);
    expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a", Interval: "P1D" }, { Text: "b", Interval: " P1D " }] }] })).not.toThrow();
    expect(() => normalizeCertificate({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "a" }, { Text: "b", Interval: null }] }] })).not.toThrow();
  });
});

describe("normalizeCertificate: nested sections", () => {
  const section = (name: string, value: unknown) => refusal(withCert({ [name]: value }));

  it("checks every section is an object with known fields", () => {
    for (const name of ["AdministrativeData", "Surgery", "Autopsy", "MannerOfDeath", "FetalOrInfantDeath", "MaternalDeath"]) {
      expect(section(name, "x")).toEqual({ path: `certificate.${name}`, message: "Must be an object." });
      expect(section(name, null)).toEqual({ path: `certificate.${name}`, message: "Must be an object." });
      expect(section(name, { Bogus: 1 })).toEqual({ path: `certificate.${name}`, message: "Contains unsupported fields." });
    }
    expect(section("Surgery", { constructor: 1 })).toEqual({ path: "certificate.Surgery", message: "Contains unsupported fields." });
    expect(section("FetalOrInfantDeath", { toString: 1 })).toEqual({ path: "certificate.FetalOrInfantDeath", message: "Contains unsupported fields." });
  });

  it("checks dates", () => {
    const date = (value: unknown) => section("AdministrativeData", { DateBirth: value });
    const at = "certificate.AdministrativeData.DateBirth";
    for (const bad of [5, "", "  ", "x".repeat(65), "tomorrow", "0000", "2026-13", "2026-00", "2026-02-30", "2023-02-29", "2026-04-31", "2026-01-00", "2026-01-32", "2026-03-04T24:00", "2026-03-04T10:60", "2026-03-04T10:00:60", "2026-03-04T10:00+24:00", "2026-03-04T10:00+05:60", "2026-03T10:00", "2026T10:00"]) {
      expect(date(bad)).toEqual({ path: at, message: "Must be a valid date." });
    }
    for (const good of ["2026", "2026-03", "2026-03-04", "2024-02-29", "2000-02-29", "2026-12-31", "2026-03-04T10:00", "2026-03-04T10:00:30", "2026-03-04T10:00:30.5Z", "2026-03-04T23:59+05:30", " 2026-03-04 "]) {
      expect(() => normalizeCertificate(withCert({ AdministrativeData: { DateBirth: good } }))).not.toThrow();
    }
    expect(normalizeCertificate(withCert({ AdministrativeData: { DateBirth: " 2026-03-04 " } })).AdministrativeData).toEqual({ DateBirth: "2026-03-04" });
    expect(section("AdministrativeData", { DateBirth: "1900-02-29" }).message).toBe("Must be a valid date."); // 1900 was not a leap year
  });

  it("checks sex, age, durations and integers", () => {
    const sex = (value: unknown) => section("AdministrativeData", { Sex: value });
    expect(sex("1")).toEqual({ path: "certificate.AdministrativeData.Sex", message: "Must be an integer." });
    expect(sex(true)).toEqual({ path: "certificate.AdministrativeData.Sex", message: "Must be an integer." });
    expect(sex(1.5)).toEqual({ path: "certificate.AdministrativeData.Sex", message: "Must be an integer." });
    expect(sex(3)).toEqual({ path: "certificate.AdministrativeData.Sex", message: "Contains an unsupported value." });
    expect(section("AdministrativeData", { EstimatedAge: "old" })).toEqual({ path: "certificate.AdministrativeData.EstimatedAge", message: "Must be a valid ISO 8601 duration." });
    expect(section("AdministrativeData", { EstimatedAge: 5 })).toEqual({ path: "certificate.AdministrativeData.EstimatedAge", message: "Must be a valid ISO 8601 duration." });
  });

  it("checks text fields, enumerations and the fetal measurements", () => {
    expect(section("Surgery", { WasPerformed: 1, Reason: " " })).toEqual({ path: "certificate.Surgery.Reason", message: "Must be non-empty text." });
    expect(section("Surgery", { WasPerformed: 1, Reason: "r".repeat(501) })).toEqual({ path: "certificate.Surgery.Reason", message: "Must be 500 characters or fewer." });
    expect(section("MannerOfDeath", { MannerOfDeath: 8 })).toEqual({ path: "certificate.MannerOfDeath.MannerOfDeath", message: "Contains an unsupported value." });
    expect(section("MannerOfDeath", { MannerOfDeath: 1, PlaceOfOccuranceExternalCause: 10 })).toEqual({ path: "certificate.MannerOfDeath.PlaceOfOccuranceExternalCause", message: "Contains an unsupported value." });
    expect(section("MaternalDeath", { TimeFromPregnancy: 4 })).toEqual({ path: "certificate.MaternalDeath.TimeFromPregnancy", message: "Contains an unsupported value." });
    expect(section("FetalOrInfantDeath", { BirthWeight: 0 })).toEqual({ path: "certificate.FetalOrInfantDeath.BirthWeight", message: "Must be at least 1." });
    expect(section("FetalOrInfantDeath", { BirthWeight: 10000 })).toEqual({ path: "certificate.FetalOrInfantDeath.BirthWeight", message: "Must be at most 9999." });
    expect(section("FetalOrInfantDeath", { DeathWithin24h: 25 })).toEqual({ path: "certificate.FetalOrInfantDeath.DeathWithin24h", message: "Must be at most 24." });
    expect(section("FetalOrInfantDeath", { PregnancyWeeks: 51 }).message).toBe("Must be at most 50.");
    expect(section("FetalOrInfantDeath", { AgeMother: 9 }).message).toBe("Must be at least 10.");
    expect(section("FetalOrInfantDeath", { PerinatalDescription: "" }).message).toBe("Must be non-empty text.");
    expect(section("FetalOrInfantDeath", { MultiplePregnancy: 2 }).message).toBe("Contains an unsupported value.");
  });

  it("leaves out unknown fetal measurements given as null or empty, but not other unknowns", () => {
    const result = normalizeCertificate(withCert({
      AdministrativeData: { EstimatedAge: "P2D" },
      FetalOrInfantDeath: { BirthWeight: null, PregnancyWeeks: "", AgeMother: null, Stillborn: 0, PerinatalDescription: "  preterm " },
    }));
    expect(result.FetalOrInfantDeath).toEqual({ Stillborn: 0, PerinatalDescription: "preterm" });
    expect(section("FetalOrInfantDeath", { Stillborn: null }).message).toBe("Must be an integer.");
  });
});

describe("dropInapplicableSections (rules V1 to V6)", () => {
  const drop = (certificate: Json) => ({ dropped: dropInapplicableSections(certificate), certificate });

  it("drops the fetal block for an adult and the 24-hour answer for a week-old or stillborn infant", () => {
    expect(drop({ AdministrativeData: { EstimatedAge: "P1Y" }, FetalOrInfantDeath: { Stillborn: 0, BirthWeight: 2000 } }).certificate).not.toHaveProperty("FetalOrInfantDeath");
    expect(drop({ AdministrativeData: { EstimatedAge: "P365D" }, FetalOrInfantDeath: { Stillborn: 0 } }).dropped).toEqual(["FetalOrInfantDeath.Stillborn"]);
    expect(drop({ AdministrativeData: { EstimatedAge: "P8D" }, FetalOrInfantDeath: { DeathWithin24h: 3, Stillborn: 0 } }))
      .toEqual({ dropped: ["FetalOrInfantDeath.DeathWithin24h"], certificate: { AdministrativeData: { EstimatedAge: "P8D" }, FetalOrInfantDeath: { Stillborn: 0 } } });
    expect(drop({ FetalOrInfantDeath: { Stillborn: 1, DeathWithin24h: 3 } }).dropped).toEqual(["FetalOrInfantDeath.DeathWithin24h"]);
    expect(drop({ AdministrativeData: { EstimatedAge: "PT5H" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual([]);
    expect(drop({ AdministrativeData: { EstimatedAge: "P6D" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual([]);
  });

  it("treats an unknown or odd age as hiding nothing", () => {
    for (const age of [undefined, "P", "PT", "P1Y2M", "old", 5]) {
      const certificate: Json = { FetalOrInfantDeath: { DeathWithin24h: 3 }, ...(age === undefined ? {} : { AdministrativeData: { EstimatedAge: age } }) };
      expect(drop(certificate).dropped).toEqual([]);
    }
    expect(drop({ AdministrativeData: { EstimatedAge: "P2W" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual(["FetalOrInfantDeath.DeathWithin24h"]);
    expect(drop({ AdministrativeData: { EstimatedAge: "PT90M" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual([]);
    expect(drop({ AdministrativeData: { EstimatedAge: "PT90S" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual([]);
    expect(drop({ AdministrativeData: { EstimatedAge: "P1M" }, FetalOrInfantDeath: { DeathWithin24h: 3 } }).dropped).toEqual(["FetalOrInfantDeath.DeathWithin24h"]);
  });

  it("keeps the maternal block only for a pregnant woman", () => {
    expect(drop({ AdministrativeData: { Sex: 1 }, MaternalDeath: { WasPregnant: 1 } }).certificate).not.toHaveProperty("MaternalDeath");
    expect(drop({ MaternalDeath: { WasPregnant: 1 } }).certificate).not.toHaveProperty("MaternalDeath");
    expect(drop({ AdministrativeData: { Sex: 2 }, MaternalDeath: { WasPregnant: 0, TimeFromPregnancy: 1, PregnancyContribute: 1 } }))
      .toEqual({ dropped: ["MaternalDeath.TimeFromPregnancy", "MaternalDeath.PregnancyContribute"], certificate: { AdministrativeData: { Sex: 2 }, MaternalDeath: { WasPregnant: 0 } } });
    expect(drop({ AdministrativeData: { Sex: 2 }, MaternalDeath: { WasPregnant: 1, TimeFromPregnancy: 1 } }).dropped).toEqual([]);
  });

  it("drops surgery details, autopsy findings and external-cause fields their parent answers hide", () => {
    expect(drop({ Surgery: { WasPerformed: 0, Date: "2026", Reason: "r" } }).dropped).toEqual(["Surgery.Date", "Surgery.Reason"]);
    expect(drop({ Surgery: { Date: "2026" } }).certificate).not.toHaveProperty("Surgery");
    expect(drop({ Surgery: { WasPerformed: 1, Date: "2026", Reason: "r" } }).dropped).toEqual([]);
    expect(drop({ Autopsy: { WasRequested: 0, Findings: 1 } }).dropped).toEqual(["Autopsy.Findings"]);
    expect(drop({ Autopsy: { WasRequested: 1, Findings: 1 } }).dropped).toEqual([]);
    const external = { DateOfExternalCauseOrPoisoning: "2026", DescriptionExternalCause: "fall", PlaceOfOccuranceExternalCause: 1 };
    expect(drop({ MannerOfDeath: { MannerOfDeath: 0, ...external } }).dropped).toHaveLength(3);
    expect(drop({ MannerOfDeath: { MannerOfDeath: 8, ...external } }).dropped).toHaveLength(3);
    expect(drop({ MannerOfDeath: { ...external } }).certificate).not.toHaveProperty("MannerOfDeath");
    expect(drop({ MannerOfDeath: { MannerOfDeath: 1, ...external } }).dropped).toEqual([]);
    expect(drop({ MannerOfDeath: { MannerOfDeath: 7, ...external } }).dropped).toEqual([]);
    expect(drop({ MannerOfDeath: { MannerOfDeath: "1", ...external } }).dropped).toHaveLength(3);
    expect(drop({}).dropped).toEqual([]);
  });

  it("runs inside normalizeCertificate: a stale client cannot send what the answers hide", () => {
    const result = normalizeCertificate(withCert({ AdministrativeData: { EstimatedAge: "P40Y", Sex: 1 }, FetalOrInfantDeath: { Stillborn: 0 }, MaternalDeath: { WasPregnant: 1 } }));
    expect(result).not.toHaveProperty("FetalOrInfantDeath");
    expect(result).not.toHaveProperty("MaternalDeath");
  });
});

describe("whoSafeCertificate", () => {
  it("leaves a year-only date out of the WHO copy when both dates are present, and keeps the original", () => {
    const certificate = { AdministrativeData: { DateBirth: "1960", DateDeath: "2026-03-04", Sex: 1 } };
    expect(whoSafeCertificate(certificate)).toEqual([{ AdministrativeData: { DateDeath: "2026-03-04", Sex: 1 } }, ["AdministrativeData.DateBirth"]]);
    expect(certificate.AdministrativeData.DateBirth).toBe("1960");
    expect(whoSafeCertificate({ AdministrativeData: { DateBirth: "1960", DateDeath: "2026" } })[1]).toEqual(["AdministrativeData.DateBirth", "AdministrativeData.DateDeath"]);
  });

  it("keeps month precision, a lone year, and a certificate without administrative data", () => {
    expect(whoSafeCertificate({ AdministrativeData: { DateBirth: "1960-05", DateDeath: "2026-03" } })[1]).toEqual([]);
    expect(whoSafeCertificate({ AdministrativeData: { DateBirth: "1960" } })[1]).toEqual([]);
    expect(whoSafeCertificate({ AdministrativeData: { DateDeath: "2026" } })[1]).toEqual([]);
    expect(whoSafeCertificate({ Part1: [] })).toEqual([{ Part1: [] }, []]);
  });
});

describe("canonicalJson", () => {
  it("sorts keys and writes no spaces, like json.dumps(sort_keys=True, separators=(',', ':'), ensure_ascii=False)", () => {
    expect(canonicalJson({ b: [1, { d: null, c: true }], a: "é\"\n" })).toBe('{"a":"é\\"\\n","b":[1,{"c":true,"d":null}]}');
    expect(canonicalJson([])).toBe("[]");
    expect(canonicalJson(3)).toBe("3");
  });
});

describe("expectedExpressionUri and verifyCertificateCodes", () => {
  const info: Record<string, Json | null> = {
    "CA40.Z": { code: "CA40.Z", stemId: "http://id.who.int/icd/release/11/2026-01/mms/1/unspecified" },
    "1B12.2": { code: "1B12.2", stemId: "http://id.who.int/icd/release/11/2026-01/mms/2" },
    XA0G74: { code: "XA0G74", stemId: "http://id.who.int/icd/release/11/2026-01/mms/3" },
    "1B12.2&XA0G74": { code: "1B12.2&XA0G74", stemId: "x" },
    "1B12.2 / CA40.Z": { code: "1B12.2 / CA40.Z", stemId: "x" },
    "1B12.2&NOSTEM": { code: "1B12.2&NOSTEM", stemId: "x" },
    NOSTEM: { code: "NOSTEM" },
    "1B12.2&WRONG": { code: "1B12.2&WRONG", stemId: "x" },
    WRONG: { code: "SOMETHING_ELSE", stemId: "y" },
    "1B12.2&MISSING": { code: "1B12.2&MISSING" },
    EMPTY: { code: "EMPTY", stemId: "" },
  };
  const who = { codeinfo: jest.fn(async (code: string) => info[code] ?? null) } as unknown as WhoEngineApi;
  const uri = (id: number, tail = "") => `http://id.who.int/icd/release/11/2026-01/mms/${id}${tail}`;

  it("is the stem URI for a stem and the parts joined by their separators for an expression", async () => {
    await expect(expectedExpressionUri(who, "CA40.Z")).resolves.toBe(uri(1, "/unspecified"));
    await expect(expectedExpressionUri(who, "1B12.2&XA0G74")).resolves.toBe(`${uri(2)} & ${uri(3)}`);
    await expect(expectedExpressionUri(who, "1B12.2 / CA40.Z")).resolves.toBe(`${uri(2)} / ${uri(1, "/unspecified")}`);
  });

  it("is null when WHO does not know the code or any part, or a stem has no URI", async () => {
    for (const code of ["UNKNOWN", "EMPTY", "NOSTEM", "1B12.2&NOSTEM", "1B12.2&WRONG", "1B12.2&MISSING"]) {
      await expect(expectedExpressionUri(who, code)).resolves.toBeNull();
    }
    await expect(expectedExpressionUri({ codeinfo: async () => ({ code: "OTHER" }) } as unknown as WhoEngineApi, "CA40.Z")).resolves.toBeNull();
  });

  const certificate = (conditions: Json[], part2: Json[] = []) => ({
    Part1: [{ Conditions: conditions }],
    ...(part2.length ? { Part2: { Conditions: part2 } } : {}),
  });

  it("passes a certificate whose URIs match, skipping uncoded conditions, and checks Part II too", async () => {
    await expect(verifyCertificateCodes(who, certificate([{ Text: "a" }, { Text: "b", Code: "CA40.Z", LinearizationURI: uri(1, "/unspecified") }], [{ Text: "c", Code: "1B12.2&XA0G74", LinearizationURI: `${uri(2)} & ${uri(3)}` }]))).resolves.toBeUndefined();
    await expect(verifyCertificateCodes(who, { Part1: [{ Conditions: [{ Text: "a" }] }], Part2: null })).resolves.toBeUndefined();
  });

  it("names the first condition whose URI does not match", async () => {
    const mismatch = { Text: "x", Code: "CA40.Z", LinearizationURI: uri(9) };
    await expect(verifyCertificateCodes(who, certificate([{ Text: "a" }, mismatch]))).rejects.toMatchObject({
      fields: [{ path: "certificate.Part1[0].Conditions[1].LinearizationURI", message: "Does not match the selected ICD-11 code." }],
    });
    await expect(verifyCertificateCodes(who, certificate([{ Text: "a" }], [mismatch]))).rejects.toMatchObject({
      fields: [{ path: "certificate.Part2.Conditions[0].LinearizationURI", message: "Does not match the selected ICD-11 code." }],
    });
    await expect(verifyCertificateCodes(who, certificate([{ Text: "a", Code: "UNKNOWN", LinearizationURI: uri(1) }]))).rejects.toBeInstanceOf(DorisCertificateError);
  });
});
