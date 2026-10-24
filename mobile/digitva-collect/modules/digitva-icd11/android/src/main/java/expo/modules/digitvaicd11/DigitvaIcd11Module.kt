package expo.modules.digitvaicd11

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/**
 * JS face of the offline WHO ICD-11 / DORIS engine (private/icd11-offline-spike, the same ICD-API 2.6.0 code as the
 * server). The engine lives in the ":icd11" process (Icd11Service); this class only forwards requests to it and
 * resolves the JS promises, so the UI process never blocks or loads the engine. The service serializes requests; init
 * happens once per service process and a failed init is sticky until that process restarts. Engine error payloads
 * never reach here: JS gets a status number or a short error code. Progress reports from an init become the
 * "icd11Progress" event ({ phase, percent }, percent -1 when unknown) and never resolve a promise. updateWhoFiles ends
 * the engine process on purpose; its promise then resolves with the init that runs in the new process.
 */
class DigitvaIcd11Module : Module() {
  private val mainHandler = Handler(Looper.getMainLooper())
  private val nextId = AtomicInteger(1)
  private val pending = ConcurrentHashMap<Int, Promise>()
  // Ids of pending OP_UPDATE requests. A process that dies before answering one restarts it (see lost()).
  private val updateIds = ConcurrentHashMap.newKeySet<Int>()
  private val replies = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(msg: Message) {
      if (msg.what == Icd11Service.WHAT_PROGRESS) {
        sendEvent("icd11Progress", mapOf("phase" to msg.data.getString("phase"), "percent" to msg.data.getInt("percent")))
        return
      }
      val id = msg.arg1
      val promise = pending.remove(id) ?: return
      val update = updateIds.remove(id)
      val result = Icd11Service.toMap(msg.data)
      if (result["restarting"] == true) {
        restartForUpdate(promise)
      } else {
        if (update && result["ok"] != true) dropRefresh()
        promise.resolve(result)
      }
    }
  })

  // Main thread only.
  private var service: Messenger? = null
  private var binding = false
  private val queued = mutableListOf<Message>()

  private val connection = object : ServiceConnection {
    override fun onServiceConnected(name: ComponentName, binder: IBinder) {
      service = Messenger(binder)
      binding = false
      queued.forEach { service?.send(it) }
      queued.clear()
    }

    override fun onServiceDisconnected(name: ComponentName) = lost()
    override fun onBindingDied(name: ComponentName) = lost()
    override fun onNullBinding(name: ComponentName) = lost()
  }

  /**
   * The update ended the engine process. Unbind first, so the old connection makes no disconnect callback that would
   * clear the new binding. Every other request waiting on the old process fails; [promise] is settled by the init that
   * runs in the new process.
   */
  private fun restartForUpdate(promise: Promise) {
    val context = appContext.reactContext ?: return promise.reject("ERR_ICD11_PROCESS", "engine process stopped", null)
    try {
      context.unbindService(connection)
    } catch (_: IllegalArgumentException) {
      // Not bound any more.
    }
    service = null
    binding = false
    queued.clear()
    rejectPending()
    send(Icd11Service.OP_INIT, "", promise)
  }

  /**
   * The engine process died or never bound. A pending update counts as restarting: its request may have written the
   * refresh flag, and the init in the new process reads it. That init is not an update request, so a process that dies
   * again only fails what is waiting. Anything else fails, and the next request binds again.
   */
  private fun lost() {
    service = null
    binding = false
    queued.clear()
    val update = pending.keys.firstOrNull { it in updateIds }?.let { pending.remove(it) }
    if (update != null) return restartForUpdate(update)
    rejectPending()
  }

  /** Fails every request still waiting on an engine process that is going away. */
  private fun rejectPending() {
    updateIds.clear()
    for (id in pending.keys.toList()) pending.remove(id)?.reject("ERR_ICD11_PROCESS", "engine process stopped", null)
  }

  /** A request that could not be delivered fails alone; a refresh request that never ran drops its flag. */
  private fun failRequest(id: Int) {
    val promise = pending.remove(id) ?: return
    if (updateIds.remove(id)) dropRefresh()
    promise.reject("ERR_ICD11_PROCESS", "engine process stopped", null)
  }

  /** A failed update must not leave its refresh flag for an unrelated later init to act on. */
  private fun dropRefresh() {
    appContext.reactContext?.let { EngineData.takeRefresh(it) }
  }

  private fun send(op: Int, input: String, promise: Promise) {
    val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
    val id = nextId.getAndIncrement()
    pending[id] = promise
    if (op == Icd11Service.OP_UPDATE) updateIds.add(id)
    val message = Message.obtain(null, op, id, 0).apply {
      replyTo = replies
      data = Bundle().apply { putString("input", input) }
    }
    mainHandler.post {
      val bound = service
      if (bound != null) {
        try {
          bound.send(message)
        } catch (_: Exception) {
          failRequest(id)
        }
        return@post
      }
      queued.add(message)
      if (!binding) {
        binding = true
        if (!context.bindService(Intent(context, Icd11Service::class.java), connection, Context.BIND_AUTO_CREATE)) lost()
      }
    }
  }

  override fun definition() = ModuleDefinition {
    Name("DigitvaIcd11")

    Events("icd11Progress")

    // Whether this build carries the engine library; does not start it.
    AsyncFunction("isAvailable") {
      val context = appContext.reactContext
      context != null && File(context.applicationInfo.nativeLibraryDir, "libdigitva_icd11.so").exists()
    }

    AsyncFunction("init") { promise: Promise -> send(Icd11Service.OP_INIT, "", promise) }

    // Explicit "Update WHO files": one init in a new engine process that may fetch WHO files, when online.
    AsyncFunction("updateWhoFiles") { promise: Promise -> send(Icd11Service.OP_UPDATE, "", promise) }

    AsyncFunction("call") { op: String, input: String, promise: Promise ->
      val code = Icd11Service.OPS[op]
      if (code == null) promise.reject("ERR_ICD11_OP", "unknown engine op", null) else send(code, input, promise)
    }
  }
}
