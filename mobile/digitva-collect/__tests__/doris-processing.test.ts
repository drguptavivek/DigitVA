/** DORIS and CoDEdit processing (dorisProcessing.ts): the server's _run_engine, ucod_parts, processing_extras and process_certificate. */
import { DorisCertificateError } from "../src/workspace/dorisCertificate";
import { DorisRequestError, processCertificate, processingExtras, runEngine, ucodParts } from "../src/workspace/dorisProcessing";
import { WhoUnavailableError, type ProcessorOutcome, type WhoEngineApi } from "../src/workspace/whoEngineApi";

type Json = Record<string, any>;
const who = (overrides: Partial<WhoEngineApi> = {}): WhoEngineApi => ({
  search: async () => ({ entities: [], chopped: false }),
  codeinfo: async () => null,
  entity: async () => ({ kind: "absent", status: 404 }),
  title: async () => "",
  runProcessor: async () => ({ kind: "unavailable" }),
  ...overrides,
});
const dorisResult = (overrides: Json = {}): Json => ({
  code: "1G40", stemCode: "1G40", uri: "http://id.who.int/icd/release/11/mms/622600769", stemURI: "s", report: "r", tabularReport: "t", reject: false, error: null, warning: null, ...overrides,
});
const codeditResult: Json = { report: "r", tabularReport: "t", issueIds: "" };

describe("runEngine", () => {
  const run = (name: "doris" | "codedit", outcome: ProcessorOutcome) => runEngine(who({ runProcessor: async () => outcome }), name, {});

  it("maps a failed run to unavailable and a non-JSON reply to malformed_response", async () => {
    await expect(run("doris", { kind: "unavailable" })).resolves.toEqual({ status: "unavailable", result: null });
    await expect(run("doris", { kind: "malformed" })).resolves.toEqual({ status: "malformed_response", result: null });
  });

  it("checks the reply's shape and keys as the server does", async () => {
    const malformed = { status: "malformed_response", result: null };
    await expect(run("doris", { kind: "ok", data: "text" })).resolves.toEqual(malformed);
    await expect(run("doris", { kind: "ok", data: [] })).resolves.toEqual(malformed);
    const { warning: _warning, ...missing } = dorisResult();
    await expect(run("doris", { kind: "ok", data: missing })).resolves.toEqual(malformed);
    await expect(run("doris", { kind: "ok", data: dorisResult({ reject: "false" }) })).resolves.toEqual(malformed);
    await expect(run("codedit", { kind: "ok", data: { report: "r" } })).resolves.toEqual(malformed);
  });

  it("is completed, or rejected when DORIS says reject; CoDEdit is never rejected", async () => {
    await expect(run("doris", { kind: "ok", data: dorisResult() })).resolves.toEqual({ status: "completed", result: dorisResult() });
    await expect(run("doris", { kind: "ok", data: dorisResult({ reject: true, code: "", error: "No UCOD" }) })).resolves.toMatchObject({ status: "rejected" });
    await expect(run("codedit", { kind: "ok", data: { ...codeditResult, reject: true } })).resolves.toEqual({ status: "completed", result: { ...codeditResult, reject: true } });
  });
});

describe("ucodParts", () => {
  const stem = "http://id.who.int/icd/release/11/2026-01/mms";
  const titles: Record<string, string> = { "1G40": "Sepsis, WHO", XN8P1: "Vibrio", BD54: "Heart", "5A11": "" };
  const client = (spy?: jest.Mock) => who({ title: async (token) => { spy?.(token); return titles[token] ?? ""; } });
  const certificate: Json = { Part1: [{ Conditions: [{ Code: "1G40", Text: " Sepsis (typed) " }] }], Part2: { Conditions: [{ Code: "XN8P1", Text: "typed ext" }, { Text: "no code" }, { Code: "Z", Text: "  " }, null] } };

  it("is empty when DORIS chose no code", async () => {
    for (const result of [null, {}, { code: "" }, { code: "  " }, { code: 5 }]) {
      await expect(ucodParts(client(), result as Json | null, certificate)).resolves.toEqual([]);
    }
  });

  it("splits a stem, its extensions and a postcoordinated code, with roles, URIs and titles (certificate text first)", async () => {
    const spy = jest.fn();
    const parts = await ucodParts(client(spy), {
      code: "1G40&XN8P1/BD54", uri: `${stem}/622600769 & ${stem}/194483911 / ${stem}/9`,
    }, certificate);
    expect(parts).toEqual([
      { code: "1G40", title: "Sepsis (typed)", role: "stem", uri: `${stem}/622600769` },
      { code: "XN8P1", title: "typed ext", role: "extension", uri: `${stem}/194483911` },
      { code: "BD54", title: "Heart", role: "postcoordinated", uri: `${stem}/9` },
    ]);
    expect(spy.mock.calls).toEqual([["BD54"]]); // the other two titles came from the certificate
  });

  it("leaves the URIs empty when they do not pair up with the parts, and skips empty tokens", async () => {
    const parts = await ucodParts(client(), { code: "BD54&&XN8P1", uri: "single" }, { Part1: [null, { Conditions: "x" }] });
    expect(parts).toEqual([{ code: "BD54", title: "Heart", role: "stem", uri: null }, { code: "XN8P1", title: "Vibrio", role: "extension", uri: null }]);
    expect((await ucodParts(client(), { code: "BD54", uri: 5 }, {}))[0].uri).toBeNull();
  });

  it("falls back to an empty title for an unknown code, a long one, or when a lookup fails; the result never fails", async () => {
    await expect(ucodParts(client(), { code: "5A11" }, {})).resolves.toEqual([{ code: "5A11", title: "", role: "stem", uri: null }]);
    await expect(ucodParts(client(), { code: "A".repeat(300) }, {})).resolves.toHaveLength(1);
    expect((await ucodParts(client(), { code: "A".repeat(300) }, {}))[0].title).toBe("");
    const down = jest.fn(async () => { throw new WhoUnavailableError("down"); });
    const afterOutage = await ucodParts(who({ title: down }), { code: "BD54&XN8P1/1G40" }, {});
    expect(afterOutage.map((part) => part.title)).toEqual(["", "", ""]);
    expect(down).toHaveBeenCalledTimes(1); // one outage costs one lookup, not one per code
    const odd = jest.fn(async () => { throw new TypeError("not an outage"); });
    expect((await ucodParts(who({ title: odd }), { code: "BD54&XN8P1" }, {})).map((part) => part.title)).toEqual(["", ""]);
    expect(odd).toHaveBeenCalledTimes(2);
  });
});

describe("processingExtras", () => {
  const completed = (result: Json | null) => ({ status: "completed" as const, result });

  it("notes the year-only dates left out of the WHO request", async () => {
    const both = { AdministrativeData: { DateBirth: "1960", DateDeath: "2026" }, Part1: [] };
    await expect(processingExtras(who(), completed(null), both)).resolves.toEqual({
      who_notes: ["Year-only dates left out of the WHO check: birth, death. Your entries are kept."], ucod_parts: [],
    });
    expect((await processingExtras(who(), completed(null), { AdministrativeData: { DateBirth: "1960", DateDeath: "2026-03" } })).who_notes).toEqual([
      "Year-only dates left out of the WHO check: birth. Your entries are kept.",
    ]);
  });

  it("notes DORIS's internal failure, and adds nothing for a clean result", async () => {
    const internal = await processingExtras(who(), completed(dorisResult({ code: "", error: "Internal system error: details" })), {});
    expect(internal.who_notes).toEqual([expect.stringMatching(/^WHO's DORIS failed internally/)]);
    await expect(processingExtras(who(), completed(dorisResult({ error: "Other error" })), {})).resolves.toMatchObject({ who_notes: [] });
    await expect(processingExtras(who(), completed(dorisResult({ error: null })), {})).resolves.toMatchObject({ who_notes: [] });
    await expect(processingExtras(who(), { status: "unavailable", result: null }, {})).resolves.toEqual({ who_notes: [], ucod_parts: [] });
  });
});

describe("processCertificate", () => {
  const uri = "http://id.who.int/icd/release/11/2026-01/mms/622600769";
  const certificate = (): Json => ({ ICDVersion: "ICD11", Part1: [{ Conditions: [{ Text: "Sepsis", Code: "1G40", LinearizationURI: uri }] }] });
  const digest = jest.fn(async (text: string) => `sha:${text.length}:${text.slice(0, 40)}`);
  const options = { digest, engineBinding: "engine-x" };
  const full = (runProcessor: WhoEngineApi["runProcessor"] = async (name) => ({ kind: "ok", data: name === "doris" ? dorisResult() : codeditResult })) =>
    who({ codeinfo: async (code) => (code === "1G40" ? { code, stemId: uri } : null), title: async () => "WHO Sepsis", runProcessor });

  it("normalises, verifies the codes, runs both engines and returns the server's reply (without a token)", async () => {
    const calls: [string, Json][] = [];
    const result = await processCertificate(full(async (name, cert) => { calls.push([name, cert as Json]); return { kind: "ok", data: name === "doris" ? dorisResult() : codeditResult }; }), { schema_version: 1, client_revision: 4, certificate: certificate() }, options);
    expect(calls.map(([name]) => name)).toEqual(["doris", "codedit"]);
    expect(calls[0][1].ICDMinorVersion).toBe("2026-01");
    expect(result).toEqual({
      schema_version: 1, client_revision: 4, icd_release: "2026-01",
      certificate: { ICDVersion: "ICD11", ICDMinorVersion: "2026-01", Part1: [{ Conditions: [{ Text: "Sepsis", Code: "1G40", LinearizationURI: uri }] }] },
      certificate_digest: expect.stringMatching(/^sha:/), result_digest: expect.stringMatching(/^sha:/),
      doris: { status: "completed", result: dorisResult() }, codedit: { status: "completed", result: codeditResult },
      who_notes: [], ucod_parts: [{ code: "1G40", title: "Sepsis", role: "stem", uri: dorisResult().uri }],
    });
    expect(result).not.toHaveProperty("process_token");
  });

  it("digests the canonical certificate, and the engine binding with both results", async () => {
    digest.mockClear();
    await processCertificate(full(), { schema_version: 1, client_revision: 0, certificate: certificate() }, options);
    const [[first], [second]] = digest.mock.calls;
    expect(first).toBe('{"ICDMinorVersion":"2026-01","ICDVersion":"ICD11","Part1":[{"Conditions":[{"Code":"1G40","LinearizationURI":"' + uri + '","Text":"Sepsis"}]}]}');
    expect(JSON.parse(second)).toEqual({ engine: "engine-x", icd_release: "2026-01", doris: { status: "completed", result: dorisResult() }, codedit: { status: "completed", result: codeditResult } });
  });

  it("keeps a failed or rejected engine as its own envelope", async () => {
    const result = await processCertificate(full(async (name) => (name === "doris" ? { kind: "ok", data: dorisResult({ reject: true, code: "" }) } : { kind: "unavailable" })), { schema_version: 1, client_revision: 0, certificate: certificate() }, options);
    expect(result.doris.status).toBe("rejected");
    expect(result.codedit).toEqual({ status: "unavailable", result: null });
    expect(result.ucod_parts).toEqual([]);
  });

  it("refuses a payload that is not {schema_version: 1, client_revision, certificate}", async () => {
    const valid = { schema_version: 1, client_revision: 0, certificate: certificate() };
    const bad: unknown[] = [
      null, "x", [], { ...valid, schema_version: 2 }, { client_revision: 0, certificate: certificate() }, { ...valid, extra: 1 },
      { schema_version: 1, certificate: certificate() }, { ...valid, client_revision: -1 }, { ...valid, client_revision: 1.5 }, { ...valid, client_revision: "0" },
    ];
    for (const payload of bad) await expect(processCertificate(full(), payload, options)).rejects.toBeInstanceOf(DorisRequestError);
  });

  it("refuses a certificate the server refuses, before any engine run", async () => {
    const runProcessor = jest.fn(async (): Promise<ProcessorOutcome> => ({ kind: "unavailable" }));
    await expect(processCertificate(full(runProcessor), { schema_version: 1, client_revision: 0, certificate: { ICDVersion: "ICD10" } }, options)).rejects.toBeInstanceOf(DorisCertificateError);
    const wrongUri = certificate();
    wrongUri.Part1[0].Conditions[0].LinearizationURI = `${uri}9`;
    await expect(processCertificate(full(runProcessor), { schema_version: 1, client_revision: 0, certificate: wrongUri }, options)).rejects.toMatchObject({
      fields: [{ path: "certificate.Part1[0].Conditions[0].LinearizationURI", message: "Does not match the selected ICD-11 code." }],
    });
    expect(runProcessor).not.toHaveBeenCalled();
  });

  it("passes the client's unavailability on", async () => {
    const down = who({ codeinfo: async () => { throw new WhoUnavailableError("down"); } });
    await expect(processCertificate(down, { schema_version: 1, client_revision: 0, certificate: certificate() }, options)).rejects.toBeInstanceOf(WhoUnavailableError);
  });
});
