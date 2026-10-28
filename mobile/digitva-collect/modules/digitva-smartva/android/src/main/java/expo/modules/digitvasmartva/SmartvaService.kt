package expo.modules.digitvasmartva

import android.app.Service
import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.Message
import android.os.Messenger
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.util.concurrent.Executors
import kotlin.system.measureTimeMillis

/** Serial, isolated process for CPU-heavy SmartVA scoring. Messages never contain identifiers beyond the case input. */
class SmartvaService : Service() {
  private val worker = Executors.newSingleThreadExecutor { runnable -> Thread(runnable, "smartva-engine") }
  private var initialized = false
  private var engineVersion: String? = null

  private val messenger = Messenger(object : Handler(Looper.getMainLooper()) {
    override fun handleMessage(message: Message) {
      val replyTo = message.replyTo ?: return
      val operation = message.what
      val id = message.arg1
      val input = message.data.getString("input").orEmpty()
      worker.execute {
        val response = when (operation) {
          OP_INIT -> initialize()
          OP_SCORE -> score(input)
          else -> mapOf("ok" to false, "error" to "native_error")
        }
        reply(replyTo, operation, id, response)
      }
    }
  })

  override fun onBind(intent: Intent?): IBinder = messenger.binder

  override fun onDestroy() {
    worker.shutdownNow()
    super.onDestroy()
  }

  private fun initialize(): Map<String, Any?> {
    var version: String? = null
    val duration = measureTimeMillis {
      try {
        if (!SmartVaJni.load()) return mapOf("ok" to false, "error" to "unavailable", "ms" to 0)
        version = SmartVaJni.version()?.takeIf { it.isNotBlank() }
        if (version == null) return mapOf("ok" to false, "error" to "native_error", "ms" to 0)
        engineVersion = version
        initialized = true
      } catch (_: Throwable) {
        return mapOf("ok" to false, "error" to "native_error", "ms" to 0)
      }
    }
    return mapOf("ok" to true, "version" to version, "ms" to duration)
  }

  private fun score(request: String): Map<String, Any?> {
    if (request.toByteArray(Charsets.UTF_8).size > MAX_REQUEST_BYTES) return mapOf("ok" to false, "error" to "too_large", "ms" to 0)
    if (!initialized) {
      val init = initialize()
      if (init["ok"] != true) return init
    }
    val root = try { JSONObject(request) } catch (_: JSONException) {
      return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    }
    if (root.opt("schema_version") !is Number || root.optInt("schema_version", -1) != 1) {
      return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    }
    val row = root.optJSONObject("input") ?: return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    val options = root.optJSONObject("options") ?: return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    val country = options.opt("country") as? String ?: return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    if (country.trim().isEmpty() || country.contains('\u0000')) return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    val flags = try {
      listOf("hiv", "malaria", "hce", "freetext").map { key ->
        if (!options.has(key) || options.opt(key) !is Boolean) throw JSONException("missing")
        options.getBoolean(key)
      }
    } catch (_: JSONException) {
      return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    }
    for (key in row.keys()) {
      val value = row.opt(key) as? String
      if (value == null || value.contains('\u0000')) return mapOf("ok" to false, "error" to "bad_request", "ms" to 0)
    }
    val rows = JSONArray().put(row).toString()
    var result: String? = null
    var nativeMs = 0L
    val duration = measureTimeMillis {
      try {
        result = SmartVaJni.scoreJson(rows, country, flags[0].asInt(), flags[1].asInt(), flags[2].asInt(), flags[3].asInt())
      } catch (_: Throwable) {
        result = null
      }
    }
    nativeMs = duration
    val text = result ?: return mapOf("ok" to false, "error" to "native_error", "ms" to duration)
    if (text == "TOO_LARGE") return mapOf("ok" to false, "error" to "too_large", "ms" to duration)
    if (text == "ENGINE_ERROR") return mapOf("ok" to false, "error" to "engine_error", "ms" to duration)
    if (text.toByteArray(Charsets.UTF_8).size > MAX_REPLY_BYTES) return mapOf("ok" to false, "error" to "too_large", "ms" to duration)
    return mapOf("ok" to true, "text" to text, "ms" to duration, "nativeMs" to nativeMs, "version" to engineVersion)
  }

  private fun Boolean.asInt() = if (this) 1 else 0

  private fun reply(to: Messenger, operation: Int, id: Int, values: Map<String, Any?>) {
    try {
      val text = values["text"] as? String
      val bytes = text?.toByteArray(Charsets.UTF_8)
      if (operation == OP_SCORE && bytes != null && bytes.size > REPLY_CHUNK_BYTES) {
        var offset = 0
        while (offset < bytes.size) {
          val end = minOf(offset + REPLY_CHUNK_BYTES, bytes.size)
          val last = end == bytes.size
          val bundle = Bundle().apply {
            putByteArray("chunk", bytes.copyOfRange(offset, end))
            putBoolean("last", last)
            if (offset == 0) {
              putBoolean("ok", true)
              putLong("ms", values["ms"] as Long)
              putLong("nativeMs", values["nativeMs"] as Long)
              putString("version", values["version"] as? String)
            }
          }
          to.send(Message.obtain(null, OP_SCORE_CHUNK, id, 0).apply { data = bundle })
          offset = end
        }
        return
      }
      val bundle = Bundle().apply {
        for ((key, value) in values) when (value) {
          is Boolean -> putBoolean(key, value)
          is Int -> putInt(key, value)
          is Long -> putLong(key, value)
          is String -> putString(key, value)
        }
      }
      to.send(Message.obtain(null, operation, id, 0).apply { data = bundle })
    } catch (_: Exception) {
      // Caller process exited; do not log the request or any result.
    }
  }

  companion object {
    const val OP_INIT = 0
    const val OP_SCORE = 1
    const val OP_SCORE_CHUNK = 2
    const val MAX_REQUEST_BYTES = 1024 * 1024
    const val MAX_REPLY_BYTES = 2 * 1024 * 1024
    const val REPLY_CHUNK_BYTES = 512 * 1024
  }
}
