/**
 * The single browser value-import boundary for the WHO runtime. Keeping both
 * namespaces in one module lets the web loader cache one downloaded module.
 * The preloaded entry has no nested lazy instrument edge for Metro to hoist.
 */
import * as runtime from "@drguptavivek/who-2022-va/web/preloaded";

export { runtime as core, runtime as web };
