/**
 * The VA cause bucket of an ICD-11 value from the pack bundled in the app. Native builds only (Collect Plus, online
 * and offline): it makes no network call, and the web bundle must never reach it (web-bundle-boundary test).
 */
import { findBundledVaDefinition as find } from "./vaDefinitions";
import pack from "../../assets/va-definitions-WHO_2022_VA_2026.json";
import { createVaDefinitionIndex, type VaDefinitionIndex, type VaDefinitionsPack } from "./vaDefinitions";
import type { VaDefinition } from "../workspace/contracts";

let index: Promise<VaDefinitionIndex> | undefined;

/** The bucket, or null when the stem is in no pack entry (not mapped). Rejects when the value has no ICD-11 stem. */
export async function getBundledVaDefinition(value: string, primaryStem?: string): Promise<VaDefinition | null> {
  index ??= createVaDefinitionIndex(pack as unknown as VaDefinitionsPack);
  const found = find(await index, value, primaryStem);
  if (found === undefined) throw new Error("va_definition_unavailable");
  return found;
}
