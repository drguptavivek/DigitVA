package expo.modules.digitvaicd11

/** JNI surface of src/main/cpp/shim.c. Single-threaded use only (see DigitvaIcd11Module). */
internal object EngineJni {
  private var shimLoaded = false

  /**
   * Loads the OpenSSL libraries (build.gradle) into this process. The engine's runtime finds them by name once they are
   * loaded, so a fetch can run; false when they are not in this build.
   */
  fun loadOpenSsl(): Boolean =
    try {
      System.loadLibrary("crypto")
      System.loadLibrary("ssl")
      true
    } catch (_: UnsatisfiedLinkError) {
      false
    }

  /** Loads the shim library; false when it is not in this build. */
  fun loadShim(): Boolean {
    if (shimLoaded) return true
    shimLoaded = try {
      System.loadLibrary("digitvaicd11shim")
      true
    } catch (_: UnsatisfiedLinkError) {
      false
    }
    return shimLoaded
  }

  /**
   * 0 on success, else a small code; never an engine message: 1 the path could not be read, 2 `dlopen` failed, 3 the library lacks
   * `digitva_icd11_init`, `digitva_icd11_free` or `digitva_icd11_call` (an engine from before 2026.10.29), which is refused.
   */
  @JvmStatic external fun load(path: String): Int

  /** 0 on success, 1 when the engine reported an error, 2 when [load] has not succeeded. */
  @JvmStatic external fun initEngine(bundleDir: String, dataDir: String): Int

  /**
   * One call: op name and JSON arguments (the bridge's `digitva_icd11_call`; Bridge.cs holds the list of ops). Null when no engine
   * is loaded or it returns nothing; status[0] receives the engine's status.
   */
  @JvmStatic external fun callOp(op: String, json: String, status: IntArray): ByteArray?
}
