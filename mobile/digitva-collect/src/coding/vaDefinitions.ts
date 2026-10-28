import { CryptoDigestAlgorithm, digestStringAsync } from "expo-crypto";

import { extractIcd11CodeExpression, firstStem } from "./icd11Allowability";
import type { VaDefinition } from "../workspace/contracts";

export interface VaDefinitionsPack {
  schema: number;
  scheme: string;
  release: string;
  source_digest: string;
  content_sha256: string;
  count: number;
  definitions: Record<string, { title: string; definition_html: string }>;
  codes: Record<string, string>;
}

export interface VaDefinitionIndex {
  definitions: Readonly<Record<string, { title: string; definition_html: string }>>;
  codes: Readonly<Record<string, string>>;
}

const HEX_SHA256 = /^[0-9a-f]{64}$/;
const VA_CODE = /^VAs-(?:\d{2}\.\d{2}|99)$/;
const ICD11_STEM = /^[0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?$/;

function canonicalContent(pack: VaDefinitionsPack): string {
  return JSON.stringify({
    schema: pack.schema,
    scheme: pack.scheme,
    release: pack.release,
    source_digest: pack.source_digest,
    count: pack.count,
    definitions: pack.definitions,
    codes: pack.codes,
  });
}

export async function createVaDefinitionIndex(
  source: unknown,
  digest: (value: string) => Promise<string> = (value) => digestStringAsync(CryptoDigestAlgorithm.SHA256, value),
): Promise<VaDefinitionIndex> {
  if (typeof source !== "object" || source === null) throw new Error("va_definitions_pack_invalid");
  const value = source as Partial<VaDefinitionsPack>;
  if (value.schema !== 1 || value.scheme !== "WHO_2022_VA_2026"
      || typeof value.release !== "string" || !value.release
      || typeof value.source_digest !== "string" || !HEX_SHA256.test(value.source_digest)
      || typeof value.content_sha256 !== "string" || !HEX_SHA256.test(value.content_sha256)
      || !Number.isSafeInteger(value.count) || typeof value.definitions !== "object" || value.definitions === null
      || Array.isArray(value.definitions) || typeof value.codes !== "object" || value.codes === null || Array.isArray(value.codes)) {
    throw new Error("va_definitions_pack_invalid");
  }
  const entries = Object.entries(value.codes);
  if (entries.length !== value.count) throw new Error("va_definitions_pack_invalid");
  for (const [code, mapping] of entries) {
    if (!ICD11_STEM.test(code) || typeof mapping !== "string"
        || !VA_CODE.test(mapping) || !(mapping in value.definitions)) throw new Error("va_definitions_pack_invalid");
  }
  for (const [code, definition] of Object.entries(value.definitions)) {
    if (!VA_CODE.test(code) || !definition || typeof definition.title !== "string" || typeof definition.definition_html !== "string") {
      throw new Error("va_definitions_pack_invalid");
    }
  }
  const content = await digest(canonicalContent(value as VaDefinitionsPack));
  if (content !== value.content_sha256) throw new Error("va_definitions_pack_invalid");
  return { definitions: value.definitions, codes: value.codes };
}

export function findBundledVaDefinition(index: VaDefinitionIndex, value: string, primaryStem?: string): VaDefinition | null {
  const expression = extractIcd11CodeExpression(value);
  const code = primaryStem ? firstStem(primaryStem) : expression && firstStem(expression);
  if (!code) return null;
  const vaCode = index.codes[code];
  const definition = vaCode && index.definitions[vaCode];
  return vaCode && definition ? {
    icd_code: code,
    classification: "icd11",
    va_code: vaCode,
    title: definition.title,
    definition_html: definition.definition_html,
  } : null;
}

