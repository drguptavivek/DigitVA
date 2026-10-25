import type { WhoCoreRuntime } from "../whoCoreRuntime";

export type WhoWebRuntime = typeof import("@drguptavivek/who-2022-va/web");
export type WhoRuntimeModule = { core: WhoCoreRuntime; web: WhoWebRuntime };

type WhoRuntimeModuleImporter = () => Promise<WhoRuntimeModule>;

/** @internal Factory kept injectable so the cache/retry contract can be tested without a VM-module runner. */
export function createWhoRuntimeLoader(importer: WhoRuntimeModuleImporter = () => import("./whoRuntimeModule")) {
  let modulePromise: Promise<WhoRuntimeModule> | undefined;

  function loadWhoRuntimeModule(): Promise<WhoRuntimeModule> {
    if (modulePromise) return modulePromise;

    const loading = importer();
    modulePromise = loading;
    // A failed download must not poison this process for a later retry.
    void loading.catch(() => {
      if (modulePromise === loading) modulePromise = undefined;
    });
    return loading;
  }

  return {
    loadWhoCoreRuntime: (): Promise<WhoCoreRuntime> => loadWhoRuntimeModule().then(({ core }) => core),
    loadWhoWebRuntime: (): Promise<WhoWebRuntime> => loadWhoRuntimeModule().then(({ web }) => web),
  };
}

const browserWhoRuntime = createWhoRuntimeLoader();

/** Load the shared WHO core namespace once in a browser session. */
export const loadWhoCoreRuntime = browserWhoRuntime.loadWhoCoreRuntime;

/** Load the browser controls namespace from the same downloaded module. */
export const loadWhoWebRuntime = browserWhoRuntime.loadWhoWebRuntime;
