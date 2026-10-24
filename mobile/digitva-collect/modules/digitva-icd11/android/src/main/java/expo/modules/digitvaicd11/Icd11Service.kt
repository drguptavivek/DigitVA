package expo.modules.digitvaicd11

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import java.util.concurrent.Executors

/**
 * Hosts the engine in its own process (":icd11", see AndroidManifest.xml): its ~600 MB resident set stays out of the
 * UI process, and an engine crash or low-memory kill takes down only this process (the next request restarts it).
 *
 * One worker thread owns the engine, so requests are serialized in arrival order. Messages: what = op (OP_*),
 * arg1 = request id echoed in the reply, data["input"] = request text; replyTo receives the result as a Bundle.
 */
class Icd11Service : Service() {
  private val worker = Executors.newSingleThreadExecutor { task ->
    // NativeAOT start-up is stack hungry; do not rely on the platform default.
    Thread(null, task, "icd11-engine", 32L shl 20)
  }
  private val host by lazy { EngineHost(applicationContext) }

  private val messenger = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(msg: Message) {
      val replyTo = msg.replyTo ?: return
      val op = msg.what
      val id = msg.arg1
      val input = msg.data.getString("input").orEmpty()
      worker.execute {
        val result = try {
          if (op == OP_INIT) host.init() else host.call(OP_NAMES[op] ?: "", input)
        } catch (_: Throwable) {
          mapOf("ok" to false, "error" to "native_error")
        }
        try {
          replyTo.send(Message.obtain(null, op, id, 0).apply { data = toBundle(result) })
        } catch (_: Exception) {
          // The app process went away; nobody is waiting.
        }
      }
    }
  })

  override fun onBind(intent: Intent?): IBinder = messenger.binder

  companion object {
    const val OP_INIT = 0
    val OP_NAMES = mapOf(1 to "search", 2 to "codeinfo", 3 to "doris", 4 to "codedit")
    val OPS = OP_NAMES.entries.associate { it.value to it.key }
    private const val MAX_TEXT_BYTES = 700_000 // Binder transactions are capped near 1 MB.

    fun toBundle(map: Map<String, Any?>): Bundle = Bundle().apply {
      for ((key, value) in map) {
        when (value) {
          is Boolean -> putBoolean(key, value)
          is Int -> putInt(key, value)
          is Double -> putDouble(key, value)
          is String -> if (key == "text" && value.length > MAX_TEXT_BYTES) {
            putBoolean("ok", false)
            putString("error", "too_large")
          } else {
            putString(key, value)
          }
        }
      }
    }

    fun toMap(bundle: Bundle): Map<String, Any?> =
      bundle.keySet().associateWith { key -> @Suppress("DEPRECATION") bundle.get(key) }
  }
}
