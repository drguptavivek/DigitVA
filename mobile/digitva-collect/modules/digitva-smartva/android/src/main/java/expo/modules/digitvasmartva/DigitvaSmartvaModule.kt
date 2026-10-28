package expo.modules.digitvasmartva

import android.content.Context
import android.content.Intent
import android.content.ServiceConnection
import android.content.ComponentName
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import java.io.ByteArrayOutputStream
import java.nio.charset.StandardCharsets
import expo.modules.kotlin.Promise
import expo.modules.kotlin.exception.Exceptions
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger

/** Expo bridge for the Plus-only, demand-started SmartVA service. */
class DigitvaSmartvaModule : Module() {
  private val main = Handler(Looper.getMainLooper())
  private val ids = AtomicInteger(1)
  private val pending = ConcurrentHashMap<Int, Promise>()
  private val queued = java.util.ArrayDeque<Message>()
  private val responseChunks = ConcurrentHashMap<Int, ByteArrayOutputStream>()
  private val chunkMetadata = ConcurrentHashMap<Int, Bundle>()
  @Volatile private var service: Messenger? = null
  @Volatile private var binding = false

  private val replies = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(message: Message) {
      val promise = pending.remove(message.arg1) ?: return
      val data = message.data
      if (message.what == SmartvaService.OP_SCORE_CHUNK) {
        pending[message.arg1] = promise
        val part = data.getByteArray("chunk") ?: run {
          responseChunks.remove(message.arg1)
          chunkMetadata.remove(message.arg1)
          pending.remove(message.arg1)?.resolve(mapOf("ok" to false, "error" to "native_error", "ms" to 0))
          return
        }
        val output = responseChunks.computeIfAbsent(message.arg1) { ByteArrayOutputStream() }
        if (output.size() + part.size > SmartvaService.MAX_REPLY_BYTES) {
          responseChunks.remove(message.arg1)
          chunkMetadata.remove(message.arg1)
          pending.remove(message.arg1)?.resolve(mapOf("ok" to false, "error" to "too_large", "ms" to 0))
          return
        }
        output.write(part)
        if (data.containsKey("ok")) chunkMetadata[message.arg1] = Bundle(data)
        if (data.getBoolean("last")) {
          val metadata = chunkMetadata.remove(message.arg1) ?: Bundle()
          val text = String(responseChunks.remove(message.arg1)?.toByteArray() ?: byteArrayOf(), StandardCharsets.UTF_8)
          val result = mapOf(
            "ok" to metadata.getBoolean("ok"),
            "text" to text,
            "ms" to metadata.getLong("ms"),
            "nativeMs" to metadata.getLong("nativeMs"),
            "version" to metadata.getString("version"),
          )
          pending.remove(message.arg1)?.resolve(result)
        }
        return
      }
      responseChunks.remove(message.arg1)
      chunkMetadata.remove(message.arg1)
      @Suppress("DEPRECATION")
      promise.resolve(data.keySet().associateWith { key -> data.get(key) })
    }
  })

  private val connection = object : ServiceConnection {
    override fun onServiceConnected(name: ComponentName, binder: IBinder) {
      service = Messenger(binder)
      binding = true
      while (queued.isNotEmpty()) dispatch(queued.removeFirst())
    }

    override fun onServiceDisconnected(name: ComponentName) {
      service = null
      failPending()
      // BIND_AUTO_CREATE will reconnect this still-live binding after the service process restarts.
    }

    override fun onBindingDied(name: ComponentName) {
      service = null
      binding = false
      failPending()
      unbind()
    }

    override fun onNullBinding(name: ComponentName) {
      service = null
      binding = false
      failPending()
      unbind()
    }
  }

  private fun failPending() {
    queued.clear()
    responseChunks.clear()
    chunkMetadata.clear()
    for (id in pending.keys.toList()) pending.remove(id)?.reject("ERR_SMARTVA_PROCESS", "SmartVA process stopped", null)
  }

  private fun unbind() {
    try { appContext.reactContext?.unbindService(connection) } catch (_: IllegalArgumentException) { }
  }

  private fun dispatch(message: Message) {
    try {
      service?.send(message) ?: run { queued.addLast(message) }
    } catch (_: Exception) {
      pending.remove(message.arg1)?.reject("ERR_SMARTVA_PROCESS", "SmartVA process stopped", null)
    }
  }

  private fun send(operation: Int, input: String, promise: Promise) {
    val context = appContext.reactContext ?: throw Exceptions.ReactContextLost()
    if (input.toByteArray(Charsets.UTF_8).size > SmartvaService.MAX_REQUEST_BYTES) {
      promise.resolve(mapOf("ok" to false, "error" to "too_large", "ms" to 0))
      return
    }
    val id = ids.getAndIncrement()
    pending[id] = promise
    val message = Message.obtain(null, operation, id, 0).apply {
      replyTo = replies
      data = Bundle().apply { putString("input", input) }
    }
    main.post {
      if (service != null) {
        dispatch(message)
        return@post
      }
      queued.addLast(message)
      if (!binding) {
        binding = true
        if (!context.bindService(Intent(context, SmartvaService::class.java), connection, Context.BIND_AUTO_CREATE)) {
          binding = false
          failPending()
        }
      }
    }
  }

  override fun definition() = ModuleDefinition {
    Name("DigitvaSmartva")

    AsyncFunction("isAvailable") {
      val context = appContext.reactContext
      context != null
          && File(context.applicationInfo.nativeLibraryDir, "libsmartva_rust.so").exists()
          && File(context.applicationInfo.nativeLibraryDir, "libsmartva_jni.so").exists()
    }

    AsyncFunction("init") { promise: Promise -> send(SmartvaService.OP_INIT, "", promise) }
    AsyncFunction("score") { request: String, promise: Promise -> send(SmartvaService.OP_SCORE, request, promise) }
  }
}
