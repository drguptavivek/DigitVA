package expo.modules.digitvaicd11

import android.content.Context
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.os.Trace
import android.system.Os
import android.util.Log
import java.io.File

/**
 * The engine's lifecycle and calls. Runs in the ":icd11" service process, on its worker thread only (see Icd11Service):
 * init once per process, failure sticky until that process restarts. The engine's error payloads can hold stack traces
 * and certificate text, so they are neither logged nor returned: callers get a status or a code.
 *
 * Network: the engine's start-up fetches WHO files (see guardNetwork). An init may fetch only when it is online with
 * OpenSSL loaded, and only for one of three reasons: (a) the first setup of an install or data reset, (b) a WHO file
 * is missing or the wrong size (EngineData.repair), (c) an explicit update (Icd11Service.refreshWhoFiles). Every other
 * init runs behind the dead proxy.
 */
internal class EngineHost(private val context: Context, private val progress: (phase: String, percent: Int) -> Unit) {
  // Touched only on the worker thread.
  private var initResult: Map<String, Any?>? = null

  /**
   * True after a fetch that failed: the process must end, so the next attempt starts a new process and falls back to
   * the shipped copies. The engine's runtime is not reused after a failed fetch.
   */
  var restartAfterInit = false
    private set

  private fun millis(since: Long) = (System.nanoTime() - since) / 1_000_000.0

  private fun fail(code: String, copyMs: Double = 0.0, initMs: Double = 0.0, totalMs: Double = 0.0) =
    mapOf("ok" to false, "error" to code, "copyMs" to copyMs, "initMs" to initMs, "ms" to totalMs, "cached" to false)

  fun init(): Map<String, Any?> {
    initResult?.let { return it + ("cached" to true) + ("ms" to 0.0) }
    val start = System.nanoTime()
    // Trace sections (Perfetto, scripts/android-trace.sh) use fixed names only; each ends in finally.
    Trace.beginSection("icd11.init")
    var fetching = false
    val result = try {
      if (!EngineJni.loadShim()) return fail("unavailable").also { initResult = it }
      val refresh = EngineData.takeRefresh(context)
      val record = EngineData.setupRecord(context)
      // A setup that started and never finished (the process died, or the fetch failed): start from shipped copies.
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
      val repair = EngineData.repair(context, root, if (interrupted) emptyMap() else EngineData.acceptedWho(record), shipped)
      fetching = (refresh || (!interrupted && (record == null || repair.repaired.isNotEmpty()))) &&
        isOnline(context) && EngineJni.loadOpenSsl()
      if (!fetching) guardNetwork()
      // The record is rewritten by a setup, and by a fetch that may change the files.
      val recordSetup = record == null || interrupted
      if (recordSetup || fetching) EngineData.markAttempt(context)
      // What the WHO files were before a fetch: the shipped copies, or the downloads still accepted.
      val before = shipped + repair.accepted
      val lib = File(context.applicationInfo.nativeLibraryDir, "libdigitva_icd11.so")
      if (!lib.exists() || EngineJni.load(lib.path) != 0) {
        fail("load_failed", copyMs, 0.0, millis(start))
      } else {
        progress(if (fetching) "setup" else "engine", -1)
        val initStart = System.nanoTime()
        val code = if (fetching) initWithBudget(File(root, "bundle").path, data.path) else EngineJni.initEngine(File(root, "bundle").path, data.path)
        val initMs = millis(initStart)
        if (code != 0) {
          // Derived files may be half written; start from clean data after a restart.
          EngineData.discard(context)
          restartAfterInit = fetching
          fail("init_failed", copyMs, initMs, millis(start))
        } else {
          val setup = if (fetching) {
            recordFetch(root, shipped, before)
          } else {
            if (recordSetup || repair.repaired.isNotEmpty()) EngineData.writeRecord(context, repair.accepted)
            EngineData.summaryOf(repair.accepted)
          }
          progress("ready", 100)
          mapOf("ok" to true, "copyMs" to copyMs, "initMs" to initMs, "ms" to millis(start), "cached" to false, "phases" to phases(root), "setup" to setup)
        }
      }
    } catch (error: Exception) {
      // Class name only: messages can carry paths or data.
      Log.w(TAG, "init failed: ${error.javaClass.simpleName}")
      restartAfterInit = fetching
      fail("data_copy_failed", 0.0, 0.0, millis(start))
    } finally {
      Trace.endSection()
    }
    initResult = result
    return result
  }

  /**
   * After a fetch: the WHO files on disk now are hashed; the ones that differ from [before] are what this run changed
   * (the summary), and the ones that differ from the shipped copies are what the record keeps.
   */
  private fun recordFetch(root: File, shipped: Map<String, EngineData.WhoFile>, before: Map<String, EngineData.WhoFile>): String {
    val now = EngineData.currentWho(root, EngineData.whoPaths(shipped))
    val changed = now.filter { (path, file) -> before[path]?.sha256 != file.sha256 }
    EngineData.writeRecord(context, now.filter { (path, file) -> shipped[path]?.sha256 != file.sha256 })
    return EngineData.summary(if (changed.isEmpty()) "shipped" else "downloaded", changed)
  }

  /**
   * At start-up the engine's DORIS and language-resource loaders try to download WHO files that are already shipped
   * (icdcdn.who.int languageResources.txt twice, icd11files.blob.core.windows.net DORIS and index zips); the engine has
   * no setting to switch that off. Without a usable OpenSSL that download aborts the process ("No usable version of
   * libssl"). A dead proxy makes each attempt fail at once, before any TLS is set up, and the engine falls back to the
   * local files. Used for every init that does not fetch.
   */
  private fun guardNetwork() {
    for (name in listOf("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY")) Os.setenv(name, "http://127.0.0.1:9", true)
  }

  /**
   * A fetching init may run long. The engine has no timeout of its own and a native call cannot be cancelled, so past
   * the budget this process is ended (the record stays "attempt", so the next attempt falls back to shipped copies).
   * The budget is the ~18 s offline init plus ~30 s for the fetches.
   */
  private fun initWithBudget(bundle: String, data: String): Int {
    val handler = Handler(Looper.getMainLooper())
    val watchdog = Runnable {
      Log.w(TAG, "fetching init timed out")
      Process.killProcess(Process.myPid())
    }
    handler.postDelayed(watchdog, SETUP_BUDGET_MS)
    try {
      return EngineJni.initEngine(bundle, data)
    } finally {
      handler.removeCallbacks(watchdog)
    }
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

  fun call(op: String, input: String): Map<String, Any?> {
    val code = OPS[op] ?: return mapOf("ok" to false, "error" to "bad_op", "status" to 0, "nativeMs" to 0.0)
    if (initResult?.get("ok") != true) {
      return mapOf("ok" to false, "error" to "not_initialized", "status" to 503, "nativeMs" to 0.0)
    }
    val status = IntArray(1)
    val start = System.nanoTime()
    // `op` is already one of OPS' fixed keys here, so the section name is never caller text.
    Trace.beginSection("icd11.$op")
    val bytes = try {
      EngineJni.call(code, input, status)
    } finally {
      Trace.endSection()
    }
    val nativeMs = millis(start)
    if (bytes == null || status[0] !in 200..299) {
      // The body of a failed call may echo the input or a stack trace: drop it.
      return mapOf("ok" to false, "error" to "engine_status", "status" to status[0], "nativeMs" to nativeMs)
    }
    return mapOf("ok" to true, "status" to status[0], "text" to String(bytes, Charsets.UTF_8), "nativeMs" to nativeMs)
  }

  private companion object {
    const val TAG = "DigitvaIcd11"
    /** A fetching init: the ~18 s offline init plus ~30 s for WHO fetches. */
    const val SETUP_BUDGET_MS = 50_000L
    val PHASES_FORMAT = Regex("[a-z]+=[0-9]+( [a-z]+=[0-9]+)*")
    val OPS = mapOf(
      "search" to EngineJni.SEARCH,
      "codeinfo" to EngineJni.CODEINFO,
      "doris" to EngineJni.DORIS,
      "codedit" to EngineJni.CODEDIT,
    )
  }
}

/** True when the active network has internet. A WHO fetch is only attempted then. */
internal fun isOnline(context: Context): Boolean {
  val manager = context.getSystemService(ConnectivityManager::class.java) ?: return false
  val capabilities = manager.activeNetwork?.let { manager.getNetworkCapabilities(it) } ?: return false
  return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
}
