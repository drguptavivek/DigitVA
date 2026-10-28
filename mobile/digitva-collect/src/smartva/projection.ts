import type { SmartVaCacheProvenance, SmartVaEnginePrediction, SmartVaEngineResult, SmartVaReference } from "./contracts";
import ICD10_BY_MODULE from "./va-icd10.json";
import ICD11_BY_ICD10 from "./va-icd11.json";

const MODULE_ICD10: Record<string, Record<string, string>> = ICD10_BY_MODULE.by_module;
const ICD11_REFERENCE: Record<string, { icd11: string; icd11_label: string | null }> = ICD11_BY_ICD10.by_icd10;

function displayText(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value !== "string" && typeof value !== "number") return null;
  if (typeof value === "number" && !Number.isFinite(value)) return null;
  const text = String(value).trim();
  return text === "" || text.toLowerCase() === "nan" ? null : text;
}

function predictionFrom(value: unknown): SmartVaEnginePrediction {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("SmartVA prediction must be an object.");
  }
  return value as SmartVaEnginePrediction;
}

/** Remove the engine's raw PII-bearing prediction shape before anything is cached or displayed. */
export function projectSmartVaResult(value: unknown): SmartVaReference {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new TypeError("SmartVA result must be an object.");
  }
  const result = value as Partial<SmartVaEngineResult>;
  if (result.total_vas !== 1 || !Array.isArray(result.predictions) || result.predictions.length !== 1) {
    throw new TypeError("SmartVA result must contain exactly one prediction.");
  }
  const prediction = predictionFrom(result.predictions[0]);
  const icd10 = displayText(prediction.icd10);
  const module = displayText(prediction.module);
  const icdMap = module ? MODULE_ICD10[module] : undefined;
  const causes: SmartVaReference["causes"] = ([1, 2, 3] as const).map((rank) => {
    const cause = displayText(prediction[`cause${rank}`]);
    const causeIcd10 = cause && icdMap ? icdMap[cause] ?? null : null;
    const icd11 = causeIcd10 ? ICD11_REFERENCE[causeIcd10] : undefined;
    return {
      rank,
      cause,
      icd10: causeIcd10,
      icd11: icd11?.icd11 ?? null,
      icd11_label: icd11?.icd11_label ?? null,
      likelihood: displayText(prediction[`likelihood${rank}`]),
    };
  });
  const rawSymptoms = displayText(prediction.all_symptoms);
  return {
    age: displayText(prediction.age),
    gender: displayText(prediction.sex),
    key_symptoms: ([1, 2, 3] as const).map((rank) => displayText(prediction[`key_symptom${rank}`])),
    causes,
    symptoms: rawSymptoms ? rawSymptoms.split(";").map((item) => item.trim()).filter(Boolean) : [],
    module,
    cause34: displayText(prediction.cause34),
    icd10,
  };
}

export function smartVaCacheKey(provenance: SmartVaCacheProvenance): string {
  for (const [name, value] of Object.entries(provenance)) {
    if (typeof value !== "string" || value.trim() === "") throw new TypeError(`SmartVA ${name} is required for cache provenance.`);
  }
  return JSON.stringify([
    provenance.draftId,
    provenance.answersSha,
    provenance.effectiveOptionsDigest,
    provenance.engineVersion,
  ]);
}
