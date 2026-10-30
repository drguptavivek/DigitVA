package expo.modules.digitvaicd11

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import android.os.TransactionTooLargeException
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
 * OP_UPDATE is retained for source compatibility but always returns bundled_only without disturbing the running engine.
 *
 * Messages: what = OP_INIT, OP_CALL or OP_UPDATE, arg1 = request id echoed in the reply, data["input"] = request text (the
 * JSON arguments of an OP_CALL) and, for OP_CALL, data["op"] = the bridge's op name (search, codeinfo, entity, ...); replyTo
 * receives the result as a Bundle. While an init runs, the worker also sends WHAT_PROGRESS bundles (phase, percent) to the same
 * replyTo; the app routes them to the icd11Progress event and never resolves a promise from them.
 */
class Icd11Service : Service() {
  private val jobs = JobScheduler()
  private val worker = Thread(null, {
    try {
      while (true) jobs.take().run()
    } catch (_: InterruptedException) {
      // Service destroyed: nothing else will be queued.
    }
  }, "icd11-engine", 32L shl 20) // NativeAOT start-up is stack hungry; do not rely on the platform default.
  private val host by lazy { EngineHost(applicationContext, ::progress) }

  // Written on the main thread, read on the worker thread.
  @Volatile private var progressTo: Messenger? = null

  private val messenger = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(msg: Message) {
      val replyTo = msg.replyTo ?: return
      val op = msg.what
      val id = msg.arg1
      val input = msg.data.getString("input").orEmpty()
      if (op == OP_UPDATE) {
        answer(replyTo, OP_UPDATE, id) { mapOf("ok" to false, "error" to "bundled_only") }
        return
      }
      if (op == OP_INIT) {
        progressTo = replyTo
        jobs.submitInit(Runnable { answer(replyTo, op, id) { host.init() } })
        return
      }
      val name = if (op == OP_CALL) msg.data.getString("op").orEmpty() else ""
      val call = Runnable { answer(replyTo, op, id) { host.call(name, input) } }
      jobs.submitCall(call)
    }
  })

  override fun onCreate() {
    super.onCreate()
    worker.start()
  }

  override fun onBind(intent: Intent?): IBinder = messenger.binder

  /** Runs [work] and replies with its map. Any throwable becomes a generic code: engine text never leaves the process. */
  private fun answer(replyTo: Messenger, op: Int, id: Int, work: () -> Map<String, Any?>) =
    answerWith(work) { map -> replyTo.send(Message.obtain(null, op, id, 0).apply { data = toBundle(map) }) }

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

  companion object {
    const val OP_INIT = 0
    /** An engine call: data["op"] names it, data["input"] holds its JSON arguments. */
    const val OP_CALL = 1
    /** Legacy update request; retained for backward compatibility and rejected as bundled_only. */
    const val OP_UPDATE = 5
    /** Reply `what` for progress reports; never a request op. */
    const val WHAT_PROGRESS = 100
    /** Lower runs first. Housekeeping has no job yet; the level is reserved so it never delays a call. */
    const val PRIORITY_INTERACTIVE = 0
    const val PRIORITY_SETUP = 1
    const val PRIORITY_HOUSEKEEPING = 2
    /** The shape of an op name (lowercase words joined by underscores); which names exist is the bridge's business. */
    val OP_NAME = Regex("[a-z_]{1,32}")
    // Binder transactions are capped near 1 MB and a Parcel stores strings as UTF-16 (2 bytes per char).
    internal const val MAX_TEXT_CHARS = 250_000

    fun toBundle(map: Map<String, Any?>): Bundle = Bundle().apply {
      for ((key, value) in boundReply(map)) {
        when (value) {
          is Boolean -> putBoolean(key, value)
          is Int -> putInt(key, value)
          is Double -> putDouble(key, value)
          is String -> putString(key, value)
        }
      }
    }

    /** [map] as it may cross Binder: a `text` over the cap becomes `{ok:false, error:"too_large"}` (the other entries stay). */
    internal fun boundReply(map: Map<String, Any?>): Map<String, Any?> {
      val text = map["text"]
      if (text !is String || text.length <= MAX_TEXT_CHARS) return map
      return (map - "text") + mapOf("ok" to false, "error" to "too_large")
    }

    /**
     * Runs [work] and hands its map to [send]. Any throwable in [work] becomes `native_error`. A send that fails with
     * TransactionTooLargeException (still over Binder's limit after the text cap) is answered with `too_large` so the caller's
     * promise settles; any other failure means the app process went away and nobody is waiting.
     */
    internal fun answerWith(work: () -> Map<String, Any?>, send: (Map<String, Any?>) -> Unit) {
      val result = try {
        work()
      } catch (_: Throwable) {
        mapOf("ok" to false, "error" to "native_error")
      }
      try {
        send(result)
      } catch (_: TransactionTooLargeException) {
        try {
          send(mapOf("ok" to false, "error" to "too_large"))
        } catch (_: Exception) {
          // The app process went away; nobody is waiting.
        }
      } catch (_: Exception) {
        // The app process went away; nobody is waiting.
      }
    }

    fun toMap(bundle: Bundle): Map<String, Any?> =
      bundle.keySet().associateWith { key -> @Suppress("DEPRECATION") bundle.get(key) }
  }
}

/**
 * The service's job queue and its init gate. Lower priority runs first, first come first served within one; a call submitted while
 * an init is queued or running is held, and joins the queue (in arrival order) when the init has answered, so no call reaches an
 * engine that is not up yet. Submissions come from the main thread, [take] and the release from the worker.
 */
internal class JobScheduler {
  private class Job(val priority: Int, val seq: Long, val task: Runnable)

  private val jobs = PriorityBlockingQueue<Job>(11, compareBy<Job>({ it.priority }, { it.seq }))
  private val seq = AtomicLong()

  private val lock = Any()
  private var initsPending = 0
  private val held = ArrayList<Runnable>()

  fun submit(priority: Int, task: Runnable) {
    jobs.put(Job(priority, seq.getAndIncrement(), task))
  }

  fun submitInit(task: Runnable) {
    synchronized(lock) { initsPending++ }
    submit(Icd11Service.PRIORITY_SETUP, Runnable {
      task.run()
      // Queued under the lock, so a call arriving meanwhile cannot take a lower seq than the ones held before it.
      synchronized(lock) {
        if (--initsPending == 0) {
          for (call in held) submit(Icd11Service.PRIORITY_INTERACTIVE, call)
          held.clear()
        }
      }
    })
  }

  fun submitCall(task: Runnable) {
    val hold = synchronized(lock) { (initsPending > 0).also { if (it) held.add(task) } }
    if (!hold) submit(Icd11Service.PRIORITY_INTERACTIVE, task)
  }

  /** Blocks until a job is queued; returns the next one by priority. */
  fun take(): Runnable = jobs.take().task
}
