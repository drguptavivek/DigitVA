package expo.modules.digitvadeviceinfo

import android.app.ActivityManager
import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import android.os.Build
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.Locale

/**
 * Coarse device characteristics for the optional app-performance aggregate.
 * No model, location, identifier or permission is exposed to JavaScript.
 */
class DigitvaDeviceInfoModule : Module() {
  private fun manufacturerBucket(): String {
    val manufacturer = Build.MANUFACTURER.lowercase(Locale.ROOT)
    return when {
      manufacturer.contains("samsung") -> "samsung"
      manufacturer.contains("google") -> "google"
      manufacturer.contains("xiaomi") || manufacturer.contains("redmi") -> "xiaomi"
      manufacturer.contains("oneplus") -> "oneplus"
      manufacturer.contains("motorola") || manufacturer.contains("lenovo") -> "motorola"
      manufacturer.contains("oppo") -> "oppo"
      manufacturer.contains("vivo") -> "vivo"
      manufacturer.contains("apple") -> "apple"
      else -> "other"
    }
  }

  private fun ramBucket(context: Context): String {
    return try {
      val info = ActivityManager.MemoryInfo()
      val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager ?: return "unknown"
      manager.getMemoryInfo(info)
      val gib = info.totalMem.toDouble() / (1024.0 * 1024.0 * 1024.0)
      when {
        gib <= 0 -> "unknown"
        gib < 2 -> "lt2"
        gib < 4 -> "2_3"
        gib < 6 -> "4_5"
        gib < 8 -> "6_7"
        gib < 12 -> "8_11"
        else -> "12plus"
      }
    } catch (_: Exception) {
      "unknown"
    }
  }

  private fun coreBucket(): String {
    return try {
      when (val cores = Runtime.getRuntime().availableProcessors()) {
        in 1..2 -> "1_2"
        in 3..4 -> "3_4"
        in 5..8 -> "5_8"
        else -> if (cores > 8) "9plus" else "unknown"
      }
    } catch (_: Exception) {
      "unknown"
    }
  }

  private fun deviceType(context: Context): String {
    val fingerprint = Build.FINGERPRINT.lowercase(Locale.ROOT)
    if (fingerprint.contains("generic") || fingerprint.contains("emulator") || Build.MODEL.lowercase(Locale.ROOT).contains("sdk")) {
      return "emulator"
    }
    return try {
      val uiMode = context.getSystemService(Context.UI_MODE_SERVICE) as? UiModeManager
      if (uiMode?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION) return "other"
      if (context.resources.configuration.smallestScreenWidthDp >= 600) "tablet" else "phone"
    } catch (_: Exception) {
      "other"
    }
  }

  override fun definition() = ModuleDefinition {
    Name("DigitvaDeviceInfo")

    Function("getHardwareProfile") {
      val context = appContext.reactContext
      if (context == null) mapOf(
          "device_type" to "other",
          "ram_bucket" to "unknown",
          "core_bucket" to "unknown",
          "manufacturer" to "unknown",
        ) else mapOf(
          "device_type" to deviceType(context),
          "ram_bucket" to ramBucket(context),
          "core_bucket" to coreBucket(),
          "manufacturer" to manufacturerBucket(),
        )
    }
  }
}
