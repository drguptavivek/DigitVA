/** Fixed native boundary for the bundled SmartVA engine. */
export interface SmartVaOptions {
  country: string;
  hiv: boolean;
  malaria: boolean;
  hce: boolean;
  freetext: boolean;
}

export interface SmartVaRequest {
  schema_version: 1;
  input: Record<string, string>;
  options: SmartVaOptions;
}

/** Standard single-case result emitted by the Rust JSON C ABI. */
export interface SmartVaEnginePrediction {
  module?: unknown;
  cause34?: unknown;
  icd10?: unknown;
  age?: unknown;
  sex?: unknown;
  cause1?: unknown;
  likelihood1?: unknown;
  key_symptom1?: unknown;
  cause2?: unknown;
  likelihood2?: unknown;
  key_symptom2?: unknown;
  cause3?: unknown;
  likelihood3?: unknown;
  key_symptom3?: unknown;
  all_symptoms?: unknown;
}

export interface SmartVaEngineResult {
  total_vas: number;
  predictions: SmartVaEnginePrediction[];
}

/** The displayed summary is compatible with the existing workspace SmartVA card. */
export interface SmartVaReference {
  age: string | null;
  gender: string | null;
  key_symptoms: Array<string | null>;
  causes: Array<{
    rank: 1 | 2 | 3;
    cause: string | null;
    icd10: string | null;
    /** Added after the original cached-result contract; absent on older cache rows. */
    icd11?: string | null;
    /** Server-equivalent WHO label, retaining ICD-11 alternative expressions. */
    icd11_label?: string | null;
    likelihood: string | null;
  }>;
  symptoms: string[];
  module: string | null;
  cause34: string | null;
  icd10: string | null;
}

export interface SmartVaCacheProvenance {
  draftId: string;
  answersSha: string;
  effectiveOptionsDigest: string;
  engineVersion: string;
}
