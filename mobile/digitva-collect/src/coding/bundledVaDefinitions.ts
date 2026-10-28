import { findBundledVaDefinition as find } from "./vaDefinitions";
import pack from "../../assets/va-definitions-WHO_2022_VA_2026.json";
import { createVaDefinitionIndex, type VaDefinitionIndex, type VaDefinitionsPack } from "./vaDefinitions";

let index: Promise<VaDefinitionIndex> | undefined;

export function getBundledVaDefinition(value: string, primaryStem?: string) {
  index ??= createVaDefinitionIndex(pack as VaDefinitionsPack);
  return index.then((resolved) => find(resolved, value, primaryStem));
}
