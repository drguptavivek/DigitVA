import type { WorkspaceApi } from "./api";

/** The COD editors' lookups and saves: the methods CaseWorkspaceScreen puts behind the ICD-11 editor gate. */
export const GUARDED_METHODS = [
  "searchIcd",
  "searchDorisTerms",
  "getDorisCodeInfo",
  "getVaDefinitionForIcd",
  "checkDorisSelection",
  "processDoris",
  "saveInitial",
  "saveFinal",
  "saveNotCodeable",
] as const;

type AnyMethod = (...args: unknown[]) => Promise<unknown>;

/**
 * `api` with every GUARDED_METHODS method awaiting `guard` before it calls through, so a refused guard sends nothing
 * and its error is the call's. Every other method is `api`'s own. One list, so a new editor method cannot forget the gate.
 */
export function withGuard(api: WorkspaceApi, guard: () => Promise<void>): WorkspaceApi {
  const guarded: Record<string, unknown> = { ...api };
  for (const name of GUARDED_METHODS) {
    guarded[name] = async (...args: unknown[]) => {
      await guard();
      return (api as unknown as Record<string, AnyMethod>)[name](...args);
    };
  }
  return guarded as unknown as WorkspaceApi;
}
