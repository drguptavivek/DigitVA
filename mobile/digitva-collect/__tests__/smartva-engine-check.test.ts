import golden from "../src/smartva/engine-check-golden.json";
import { engineCheckAutoRun, runSmartVaEngineCheck } from "../src/smartva/engineCheck";
import { type OfflineSmartvaEngine } from "../src/smartva/nativeEngine";

function engineResult(
  expected: (typeof golden.cases)[number]["expected"],
  allSymptoms: (typeof golden.cases)[number]["all_symptoms"],
): string {
  const raw = {
    total_vas: 1,
    predictions: [{
      module: expected.module,
      cause34: expected.cause34,
      icd10: expected.icd10,
      age: expected.age,
      sex: expected.gender,
      cause1: expected.causes[0].cause,
      likelihood1: expected.causes[0].likelihood,
      key_symptom1: expected.key_symptoms[0],
      cause2: expected.causes[1].cause,
      likelihood2: expected.causes[1].likelihood,
      key_symptom2: expected.key_symptoms[1],
      cause3: expected.causes[2].cause,
      likelihood3: expected.causes[2].likelihood,
      key_symptom3: expected.key_symptoms[2],
      all_symptoms: allSymptoms,
    }],
  };
  return JSON.stringify(raw);
}

describe("runSmartVaEngineCheck", () => {
  it("keeps the SmartVA deep link separate from the existing ICD-11 run link", () => {
    expect(engineCheckAutoRun("1")).toBe("icd11");
    expect(engineCheckAutoRun(undefined, "1")).toBe("smartva");
    expect(engineCheckAutoRun("1", "1")).toBe("smartva");
    expect(engineCheckAutoRun()).toBeNull();
  });

  it("scores only synthetic golden cases, checks exact output, and repeats adult warm", async () => {
    for (const fixture of golden.cases) {
      expect(fixture.expected.cause34).not.toBe("Undetermined");
      expect(fixture.expected.symptoms.length).toBeGreaterThan(0);
      expect(fixture.expected.key_symptoms.some(Boolean)).toBe(true);
    }
    const score = jest.fn(async (request) => {
      const id = request.input.sid.slice("SYNTHETIC-".length);
      const fixture = golden.cases.find((item) => item.id === id) ?? golden.cases[0];
      return { ok: true, text: engineResult(fixture.expected, fixture.all_symptoms), ms: 27, nativeMs: 24, version: golden.source.engine_version };
    });
    const engine: OfflineSmartvaEngine = {
      available: jest.fn(async () => true),
      init: jest.fn(async () => ({ ok: true, ms: 12, version: golden.source.engine_version })),
      score,
    };

    const result = await runSmartVaEngineCheck(engine);

    expect(result.ok).toBe(true);
    expect(result.cases.map(({ id, matched }) => [id, matched])).toEqual([
      ["adult", true], ["child", true], ["neonate", true],
    ]);
    expect(result.initMs).toBe(12);
    expect(result.warmRepeat).toMatchObject({ id: "adult-warm", ok: true, matched: true, ms: 27, nativeMs: 24 });
    expect(score).toHaveBeenCalledTimes(4);
    expect(score.mock.calls.map(([request]) => request.options)).toEqual(
      Array(4).fill(golden.options),
    );
    expect(JSON.stringify(result)).not.toMatch(/SYNTHETIC|ageInYears|all_symptoms|key_symptom/);
  });

  it("returns unavailable without initializing or scoring", async () => {
    const engine: OfflineSmartvaEngine = {
      available: jest.fn(async () => false),
      init: jest.fn(async () => ({ ok: false, ms: 0, error: "unavailable" })),
      score: jest.fn(),
    };
    await expect(runSmartVaEngineCheck(engine)).resolves.toMatchObject({ ok: false, available: false, cases: [] });
    expect(engine.init).not.toHaveBeenCalled();
    expect(engine.score).not.toHaveBeenCalled();
  });

  it("turns native rejections into short diagnostic codes", async () => {
    const engine: OfflineSmartvaEngine = {
      available: jest.fn(async () => true),
      init: jest.fn(async () => ({ ok: true, ms: 3, version: golden.source.engine_version })),
      score: jest.fn(async () => { throw new Error("native detail must not escape"); }),
    };

    const result = await runSmartVaEngineCheck(engine);

    expect(result.ok).toBe(false);
    expect(result.cases).toHaveLength(3);
    expect(result.cases.every((item) => item.error === "engine_error")).toBe(true);
    expect(result.warmRepeat?.error).toBe("engine_error");
    expect(JSON.stringify(result)).not.toContain("native detail");
  });

  it("returns a setup code if native initialization rejects", async () => {
    const engine: OfflineSmartvaEngine = {
      available: jest.fn(async () => true),
      init: jest.fn(async () => { throw new Error("private native error"); }),
      score: jest.fn(),
    };

    await expect(runSmartVaEngineCheck(engine)).resolves.toMatchObject({
      ok: false, available: true, error: "init_failed", cases: [],
    });
    expect(engine.score).not.toHaveBeenCalled();
  });
});
