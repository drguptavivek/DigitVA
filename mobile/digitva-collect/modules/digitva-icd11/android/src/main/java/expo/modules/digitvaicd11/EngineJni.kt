package expo.modules.digitvaicd11

/** JNI surface of src/main/cpp/shim.c. Single-threaded use only (see DigitvaIcd11Module). */
internal object EngineJni {
  /** Ops in the order shim.c indexes its function table. */
  const val SEARCH = 0
  const val CODEINFO = 1
  const val DORIS = 2
  const val CODEDIT = 3

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

  /** 0 on success, else a small code; never an engine message. */
  @JvmStatic external fun load(path: String): Int

  /** 0 on success, 1 when the engine reported an error, 2 when [load] has not succeeded. */
  @JvmStatic external fun initEngine(bundleDir: String, dataDir: String): Int

  /** Response bytes (UTF-8 JSON) or null; status[0] receives the HTTP-style status the engine reports. */
  @JvmStatic external fun call(op: Int, input: String, status: IntArray): ByteArray?
}
