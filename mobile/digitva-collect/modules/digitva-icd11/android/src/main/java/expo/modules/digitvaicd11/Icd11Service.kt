package expo.modules.digitvaicd11

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.Process
import java.util.concurrent.CompletableFuture
import java.util.concurrent.PriorityBlockingQueue
import java.util.concurrent.atomic.AtomicLong

/**
 * Hosts the engine in its own process (":icd11", see AndroidManifest.xml): its ~600 MB resident set stays out of the
 * UI process, and an engine crash or low-memory kill takes down only this process (the next request restarts it).
 *
 * One worker thread owns the engine and runs jobs from a priority queue: interactive calls (0) before the first setup
 * or init (1) before housekeeping (2), first come first served within a priority. A call that arrives while the init
 * is still queued or running waits for it, so no call reaches an engine that is not up yet. A job killed with the
 * process is simply run again by the next process: the init is idempotent and the data copy restarts cleanly.
 *
 * OP_UPDATE (the explicit "Update WHO files") is a setup-priority job too: it runs after the calls queued before it. It
 * ends this process, so the app's next init starts a new one that may fetch WHO files (EngineHost.init).
 *
 * Messages: what = op (OP_*), arg1 = request id echoed in the reply, data["input"] = request text; replyTo receives the
 * result as a Bundle. While an init runs, the worker also sends WHAT_PROGRESS bundles (phase, percent) to the same
 * replyTo; the app routes them to the icd11Progress event and never resolves a promise from them.
 */
class Icd11Service : Service() {
  private val jobs = PriorityBlockingQueue<Job>(11, compareBy<Job>({ it.priority }, { it.seq }))
  private val seq = AtomicLong()
  private val worker = Thread(null, {
    try {
      while (true) jobs.take().task.run()
    } catch (_: InterruptedException) {
      // Service destroyed: nothing else will be queued.
    }
  }, "icd11-engine", 32L shl 20) // NativeAOT start-up is stack hungry; do not rely on the platform default.
  private val host by lazy { EngineHost(applicationContext, ::progress) }

  // Main thread only. Set by an init request; a call that arrives while it is pending waits on it.
  private var initDone: CompletableFuture<Unit>? = null

  // Written on the main thread, read on the worker thread.
  @Volatile private var progressTo: Messenger? = null

  private val messenger = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(msg: Message) {
      val replyTo = msg.replyTo ?: return
      val op = msg.what
      val id = msg.arg1
      val input = msg.data.getString("input").orEmpty()
      if (op == OP_UPDATE) {
        submit(PRIORITY_SETUP, Runnable { refreshWhoFiles(replyTo, id) })
        return
      }
      if (op == OP_INIT) {
        progressTo = replyTo
        val done = CompletableFuture<Unit>()
        initDone = done
        submit(PRIORITY_SETUP, Runnable {
          answer(replyTo, op, id) { host.init() }
          done.complete(Unit)
          // A first setup that fetched and failed ends the process: the next attempt starts fresh (EngineHost).
          if (host.restartAfterInit) Process.killProcess(Process.myPid())
        })
        return
      }
      val call = Runnable { answer(replyTo, op, id) { host.call(OP_NAMES[op] ?: "", input) } }
      val pendingInit = initDone?.takeUnless { it.isDone }
      if (pendingInit == null) submit(PRIORITY_INTERACTIVE, call) else pendingInit.thenRun { submit(PRIORITY_INTERACTIVE, call) }
    }
  })

  override fun onCreate() {
    super.onCreate()
    worker.start()
  }

  override fun onBind(intent: Intent?): IBinder = messenger.binder

  private fun submit(priority: Int, task: Runnable) {
    jobs.put(Job(priority, seq.getAndIncrement(), task))
  }

  /**
   * Offline: answers "no_connection" and keeps the engine. Online: marks the refresh, replies "restarting" and ends
   * this process. The reply goes out before the process ends, as a failed fetch's does (EngineHost.init).
   */
  private fun refreshWhoFiles(replyTo: Messenger, id: Int) {
    if (!isOnline(applicationContext)) {
      answer(replyTo, OP_UPDATE, id) { mapOf("ok" to false, "error" to "no_connection") }
      return
    }
    if (!EngineData.requestRefresh(applicationContext)) {
      answer(replyTo, OP_UPDATE, id) { mapOf("ok" to false, "error" to "failed") }
      return
    }
    answer(replyTo, OP_UPDATE, id) { mapOf("ok" to true, "restarting" to true) }
    Process.killProcess(Process.myPid())
  }

  /** Runs [work] and replies with its map. Any throwable becomes a generic code: engine text never leaves the process. */
  private fun answer(replyTo: Messenger, op: Int, id: Int, work: () -> Map<String, Any?>) {
    val result = try {
      work()
    } catch (_: Throwable) {
      mapOf("ok" to false, "error" to "native_error")
    }
    try {
      replyTo.send(Message.obtain(null, op, id, 0).apply { data = toBundle(result) })
    } catch (_: Exception) {
      // The app process went away; nobody is waiting.
    }
  }

  /** Phase and percent (-1 when unknown) of the running init, for the app's icd11Progress event. Worker thread only. */
  private fun progress(phase: String, percent: Int) {
    val to = progressTo ?: return
    try {
      to.send(Message.obtain(null, WHAT_PROGRESS, 0, 0).apply {
        data = Bundle().apply {
          putString("phase", phase)
          putInt("percent", percent)
        }
      })
    } catch (_: Exception) {
      // The app process went away; nobody is listening.
    }
  }

  private class Job(val priority: Int, val seq: Long, val task: Runnable)

  companion object {
    const val OP_INIT = 0
    /** Explicit WHO-file update (EngineData.requestRefresh); a request op, handled here rather than by the engine. */
    const val OP_UPDATE = 5
    /** Reply `what` for progress reports; never a request op. */
    const val WHAT_PROGRESS = 100
    /** Lower runs first. Housekeeping has no job yet; the level is reserved so it never delays a call. */
    const val PRIORITY_INTERACTIVE = 0
    const val PRIORITY_SETUP = 1
    const val PRIORITY_HOUSEKEEPING = 2
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
