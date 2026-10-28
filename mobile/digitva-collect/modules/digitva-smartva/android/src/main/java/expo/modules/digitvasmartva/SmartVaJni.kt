package expo.modules.digitvasmartva

/** Loaded only on first demand from the isolated SmartVA service. */
object SmartVaJni {
  @Volatile private var loaded = false

  @Synchronized
  fun load(): Boolean {
    if (loaded) return true
    return try {
      System.loadLibrary("smartva_rust")
      System.loadLibrary("smartva_jni")
      loaded = true
      true
    } catch (_: UnsatisfiedLinkError) {
      false
    }
  }

  external fun version(): String?
  external fun scoreJson(payload: String, country: String, hiv: Int, malaria: Int, hce: Int, freetext: Int): String?
}
