import { compileInstrumentDefinition, type InstrumentRuntimeIndex } from "./instrument-model.js";
import type { InstrumentDefinition } from "../types.js";

export type { InstrumentRuntimeIndex } from "./instrument-model.js";

/** Builds immutable lookup indexes once for each instrument object. */
export function getInstrumentRuntimeIndex(instrument: InstrumentDefinition): InstrumentRuntimeIndex {
  return compileInstrumentDefinition(instrument).runtimeIndex;
}
