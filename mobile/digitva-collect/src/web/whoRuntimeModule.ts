/**
 * The single browser value-import boundary for the WHO runtime. Keeping both
 * namespaces in one module lets the web loader cache one downloaded module.
 */
import * as core from "@drguptavivek/who-2022-va";
import * as web from "@drguptavivek/who-2022-va/web";

export { core, web };
