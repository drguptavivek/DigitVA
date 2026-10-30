package expo.modules.digitvaicd11

import android.content.Context
import android.os.Trace
import android.system.Os
import android.util.Log
import java.io.File

/**
 * The engine's lifecycle and calls. Runs in the ":icd11" service process, on its worker thread only (see Icd11Service):
 * init once per process, failure sticky until that process restarts. The engine's error payloads can hold stack traces
 * and certificate text, so they are neither logged nor returned: callers get a status or a code.
 *
 * Every init runs behind the dead proxy: engine and WHO data are packaged together, and runtime downloads are disabled.
 */
internal class EngineHost(private val context: Context, private val progress: (phase: String, percent: Int) -> Unit) {
  // Touched only on the worker thread.
  private var initResult: Map<String, Any?>? = null

  private fun millis(since: Long) = (System.nanoTime() - since) / 1_000_000.0

  private fun fail(code: String, copyMs: Double = 0.0, initMs: Double = 0.0, totalMs: Double = 0.0) =
    mapOf("ok" to false, "error" to code, "copyMs" to copyMs, "initMs" to initMs, "ms" to totalMs, "cached" to false)

  fun init(): Map<String, Any?> {
    initResult?.let { return it + ("cached" to true) + ("ms" to 0.0) }
    val start = System.nanoTime()
    // Trace sections (Perfetto, scripts/android-trace.sh) use fixed names only; each ends in finally.
    Trace.beginSection("icd11.init")
    val result = try {
      if (!EngineJni.loadShim()) return fail("unavailable").also { initResult = it }
      val record = EngineData.setupRecord(context)
      // A setup that started and never finished: start from the packaged copies.
      val interrupted = record?.optString("state") == "attempt"
      if (interrupted) EngineData.discard(context)
      val copyStart = System.nanoTime()
      Trace.beginSection("icd11.copy")
      val root = try {
        EngineData.ensureCopied(context) { percent -> progress("copy", percent) }
      } finally {
        Trace.endSection()
      }
      val copyMs = millis(copyStart)
      val data = File(root, "data")
      // The engine's .NET runtime reads TMPDIR from the C environment.
      Os.setenv("TMPDIR", data.path + "/", true)
      val shipped = EngineData.shippedWho(context)
      val repair = EngineData.repair(context, root, shipped)
      guardNetwork()
      val recordSetup = record == null || interrupted
      if (recordSetup) EngineData.markAttempt(context)
      val lib = File(context.applicationInfo.nativeLibraryDir, "libdigitva_icd11.so")
      // load refuses a library without digitva_icd11_call (a stale engine pin): "load_failed", so the app reports the engine unavailable.
      if (!lib.exists() || EngineJni.load(lib.path) != 0) {
        fail("load_failed", copyMs, 0.0, millis(start))
      } else {
        progress("engine", -1)
        val initStart = System.nanoTime()
        val code = EngineJni.initEngine(File(root, "bundle").path, data.path)
        val initMs = millis(initStart)
        if (code != 0) {
          // Derived files may be half written; start from clean data after a restart.
          EngineData.discard(context)
          fail("init_failed", copyMs, initMs, millis(start))
        } else {
          if (recordSetup || repair.repaired.isNotEmpty()) EngineData.writeRecord(context)
          val setup = EngineData.summary("shipped", emptyMap())
          progress("ready", 100)
          mapOf("ok" to true, "copyMs" to copyMs, "initMs" to initMs, "ms" to millis(start), "cached" to false, "phases" to phases(root), "setup" to setup)
        }
      }
    } catch (error: Exception) {
      // Class name only: messages can carry paths or data.
      Log.w(TAG, "init failed: ${error.javaClass.simpleName}")
      fail("data_copy_failed", 0.0, 0.0, millis(start))
    } finally {
      Trace.endSection()
    }
    initResult = result
    return result
  }

  /**
   * At start-up the engine's DORIS and language-resource loaders try to download WHO files that are already shipped
   * (icdcdn.who.int languageResources.txt twice, icd11files.blob.core.windows.net DORIS and index zips); the engine has
   * no setting to switch that off. Without a usable OpenSSL that download aborts the process ("No usable version of
   * libssl"). A dead proxy makes each attempt fail at once, before any TLS is set up, and the engine falls back to the
   * local files. Used for every init.
   */
  private fun guardNetwork() {
    for (name in listOf("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")) Os.setenv(name, "http://127.0.0.1:9", true)
  }

  /**
   * Phase end times inside the engine's init ("config=3900 doris=12500 index=17900 ready=17901", ms since init start),
   * written by the bridge. Numbers and fixed labels only; empty if the file is missing or not in that shape.
   */
  private fun phases(root: File): String {
    val text = try {
      File(root, "init-timings.txt").readText().trim()
    } catch (_: Exception) {
      ""
    }
    return if (PHASES_FORMAT.matches(text)) text else ""
  }

  /**
   * One engine call: [op] is the bridge's op name (the allow-list is Bridge.cs's, not ours; only its shape is checked here) and
   * [input] the JSON object of its arguments.
   */
  fun call(op: String, input: String): Map<String, Any?> =
    callResult(initResult?.get("ok") == true, op, input) { name, json, status ->
      // A fixed section name: `op` is caller text.
      Trace.beginSection("icd11.call")
      try {
        EngineJni.callOp(name, json, status)
      } finally {
        Trace.endSection()
      }
    }

  private companion object {
    const val TAG = "DigitvaIcd11"
    val PHASES_FORMAT = Regex("[a-z]+=[0-9]+( [a-z]+=[0-9]+)*")
  }
}

/**
 * The result map of one call (see [EngineHost.call]): [invoke] runs the engine and fills status[0]; [initialised] is whether the
 * init succeeded. Android-free so the JVM unit tests can run it.
 */
internal fun callResult(initialised: Boolean, op: String, input: String, invoke: (String, String, IntArray) -> ByteArray?): Map<String, Any?> {
  if (!Icd11Service.OP_NAME.matches(op)) return mapOf("ok" to false, "error" to "bad_op", "status" to 0, "nativeMs" to 0.0)
  if (!initialised) return mapOf("ok" to false, "error" to "not_initialized", "status" to 503, "nativeMs" to 0.0)
  val status = IntArray(1)
  val start = System.nanoTime()
  val bytes = invoke(op, input, status)
  val nativeMs = (System.nanoTime() - start) / 1_000_000.0
  if (bytes == null || status[0] !in 200..299) {
    // The body of a failed call may echo the input or a stack trace: drop it.
    return mapOf("ok" to false, "error" to "engine_status", "status" to status[0], "nativeMs" to nativeMs)
  }
  return mapOf("ok" to true, "status" to status[0], "text" to String(bytes, Charsets.UTF_8), "nativeMs" to nativeMs)
}
