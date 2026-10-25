import * as coreRuntime from "@drguptavivek/who-2022-va";

/** The platform-neutral WHO VA runtime namespace. */
export type WhoCoreRuntime = typeof import("@drguptavivek/who-2022-va");

/** Keep the native path available synchronously to the bundler, while sharing an async contract with web. */
export async function loadWhoCoreRuntime(): Promise<WhoCoreRuntime> {
  return coreRuntime;
}
