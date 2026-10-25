import type { WhoRuntimeModule } from "../src/web/whoRuntimeLoader";
import { createWhoRuntimeLoader } from "../src/web/whoRuntimeLoader";

describe("browser WHO runtime loader", () => {
  it("shares one imported module between core and web namespace loads", async () => {
    let imports = 0;
    const { loadWhoCoreRuntime, loadWhoWebRuntime } = createWhoRuntimeLoader(async () => {
      imports += 1;
      return { core: { kind: "core" }, web: { kind: "web" } } as unknown as WhoRuntimeModule;
    });

    const [core, web, coreAgain] = await Promise.all([
      loadWhoCoreRuntime(),
      loadWhoWebRuntime(),
      loadWhoCoreRuntime(),
    ]);

    expect(core).toEqual({ kind: "core" });
    expect(web).toEqual({ kind: "web" });
    expect(coreAgain).toBe(core);
    expect(imports).toBe(1);
  });

  it("evicts a failed module download so the next attempt can retry", async () => {
    let attempts = 0;
    const { loadWhoCoreRuntime } = createWhoRuntimeLoader(async () => {
      attempts += 1;
      if (attempts === 1) throw new Error("transient download");
      return { core: { ready: true }, web: { ready: true } } as unknown as WhoRuntimeModule;
    });

    await expect(loadWhoCoreRuntime()).rejects.toThrow("transient download");
    await expect(loadWhoCoreRuntime()).resolves.toEqual({ ready: true });
    expect(attempts).toBe(2);
  });
});
