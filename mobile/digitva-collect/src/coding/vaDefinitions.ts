import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import { extractIcd11CodeExpression, firstStem } from "./icd11Allowability";
import type { VaDefinition } from "../workspace/contracts";

export interface VaBucket {
  label: string;
  section: string | null;
  section_code: string | null;
  /** The VAs form code; null when the node has none (its node code is shown instead). */
  va_code: string | null;
}

export interface VaDefinitionsPack {
  schema: number;
  scheme: string;
  release: string;
  /** The migration revision the pack was cut at. Outside the content hash. */
  db_revision: string | null;
  content_sha256: string;
  count: number;
  buckets: Record<string, VaBucket>;
  definitions: Record<string, { title: string; definition_html: string }>;
  codes: Record<string, string>;
}

export interface VaDefinitionIndex {
  buckets: Readonly<Record<string, VaBucket>>;
  definitions: Readonly<Record<string, { title: string; definition_html: string }>>;
  codes: Readonly<Record<string, string>>;
}

const HEX_SHA256 = /^[0-9a-f]{64}$/;
const ICD11_STEM = /^[0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?$/;

const isObject = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);
const isTextOrNull = (value: unknown) => value === null || typeof value === "string";

/** The exact text the exporter hashed: fixed key order (db_revision excluded), compact. */
function canonicalContent(pack: VaDefinitionsPack): string {
  return JSON.stringify({
    schema: pack.schema,
    scheme: pack.scheme,
    release: pack.release,
    count: pack.count,
    buckets: pack.buckets,
    definitions: pack.definitions,
    codes: pack.codes,
  });
}

export async function createVaDefinitionIndex(
  source: unknown,
  digest: (value: string) => Promise<string> = (value) => digestStringAsync(CryptoDigestAlgorithm.SHA256, value),
): Promise<VaDefinitionIndex> {
  if (!isObject(source)) throw new Error("va_definitions_pack_invalid");
  const value = source as Partial<VaDefinitionsPack>;
  if (value.schema !== 2 || value.scheme !== "WHO_2022_VA_2026"
      || typeof value.release !== "string" || !value.release
      || !isTextOrNull(value.db_revision)
      || typeof value.content_sha256 !== "string" || !HEX_SHA256.test(value.content_sha256)
      || !Number.isSafeInteger(value.count) || !isObject(value.buckets) || !isObject(value.definitions) || !isObject(value.codes)) {
    throw new Error("va_definitions_pack_invalid");
  }
  const entries = Object.entries(value.codes);
  if (entries.length !== value.count) throw new Error("va_definitions_pack_invalid");
  for (const [code, node] of entries) {
    if (!ICD11_STEM.test(code) || typeof node !== "string" || !Object.hasOwn(value.buckets, node)) throw new Error("va_definitions_pack_invalid");
  }
  for (const bucket of Object.values(value.buckets)) {
    if (!isObject(bucket) || typeof bucket.label !== "string" || !isTextOrNull(bucket.section) || !isTextOrNull(bucket.section_code) || !isTextOrNull(bucket.va_code)) {
      throw new Error("va_definitions_pack_invalid");
    }
  }
  for (const definition of Object.values(value.definitions)) {
    if (!isObject(definition) || typeof definition.title !== "string" || typeof definition.definition_html !== "string") {
      throw new Error("va_definitions_pack_invalid");
    }
  }
  const content = await digest(canonicalContent(value as VaDefinitionsPack));
  if (content !== value.content_sha256) throw new Error("va_definitions_pack_invalid");
  return { buckets: value.buckets, definitions: value.definitions, codes: value.codes };
}

/**
 * The VA cause bucket of an ICD-11 value, resolved by its primary stem (the saved `primaryStem`, else the first stem).
 * `undefined`: no lookup is possible (the value carries no ICD-11 stem). `null`: the stem is in no pack entry, so
 * analytics reports it unmapped. Otherwise the bucket, with its definition when its node has one in the pack.
 */
export function findBundledVaDefinition(index: VaDefinitionIndex, value: string, primaryStem?: string): VaDefinition | null | undefined {
  const expression = extractIcd11CodeExpression(value);
  const code = primaryStem ? firstStem(primaryStem) : expression && firstStem(expression);
  if (!code) return undefined;
  const node = index.codes[code];
  const bucket = node === undefined ? undefined : index.buckets[node];
  if (node === undefined || !bucket) return null;
  const definition = bucket.va_code ? index.definitions[bucket.va_code] : undefined;
  return {
    icd_code: code,
    classification: "icd11",
    va_code: bucket.va_code ?? node,
    title: definition ? definition.title : bucket.label,
    definition_html: definition ? definition.definition_html : "",
    bucket_code: node,
    bucket_label: bucket.label,
    bucket_section: bucket.section,
    has_definition: Boolean(definition),
  };
}
