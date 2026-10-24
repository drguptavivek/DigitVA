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
 * never reach here: JS gets a status number or a short error code.
 */
class DigitvaIcd11Module : Module() {
  private val mainHandler = Handler(Looper.getMainLooper())
  private val nextId = AtomicInteger(1)
  private val pending = ConcurrentHashMap<Int, Promise>()
  private val replies = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(msg: Message) {
      pending.remove(msg.arg1)?.resolve(Icd11Service.toMap(msg.data))
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

  /** The engine process died or never bound: fail what is waiting; the next request binds again. */
  private fun lost() {
    service = null
    binding = false
    queued.clear()
    val waiting = pending.keys.toList()
    for (id in waiting) pending.remove(id)?.reject("ERR_ICD11_PROCESS", "engine process stopped", null)
  }

  private fun send(op: Int, input: String, promise: Promise) {
    val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
    val id = nextId.getAndIncrement()
    pending[id] = promise
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
          pending.remove(id)?.reject("ERR_ICD11_PROCESS", "engine process stopped", null)
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

    // Whether this build carries the engine library; does not start it.
    AsyncFunction("isAvailable") {
      val context = appContext.reactContext
      context != null && File(context.applicationInfo.nativeLibraryDir, "libdigitva_icd11.so").exists()
    }

    AsyncFunction("init") { promise: Promise -> send(Icd11Service.OP_INIT, "", promise) }

    AsyncFunction("call") { op: String, input: String, promise: Promise ->
      val code = Icd11Service.OPS[op]
      if (code == null) promise.reject("ERR_ICD11_OP", "unknown engine op", null) else send(code, input, promise)
    }
  }
}
