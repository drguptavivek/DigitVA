package expo.modules.digitvaicd11

import android.content.Context
import java.io.File

/**
 * Engine data shipped as APK assets under digitva-icd11/, each file stored as "<name>.bin" (AAPT expands ".gz"
 * assets, and the engine needs the original names). Copied once into filesDir/icd11-<DATA_VERSION>/{bundle,data};
 * the engine then writes its own derived files (unzipped index, annex) next to them.
 */
internal object EngineData {
  /** Bump when the staged data changes: a new version dir is copied and older ones are deleted. */
  const val DATA_VERSION = "2026-01-17-doris-1.2.0-v2"
  private const val ASSET_ROOT = "digitva-icd11"
  private const val DIR_PREFIX = "icd11-"
  private const val DONE_MARKER = ".copied"

  fun root(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION")

  /** Copies the assets if this version is not complete yet. Returns the root dir; throws on any I/O failure. */
  fun ensureCopied(context: Context): File {
    val root = root(context)
    if (File(root, DONE_MARKER).exists()) return root
    removeOtherVersions(context)
    root.deleteRecursively()
    root.mkdirs()
    copyDir(context, ASSET_ROOT, root)
    File(root, DONE_MARKER).writeText(DATA_VERSION)
    return root
  }

  /** Forget this version's files (including engine-derived ones) so the next process start copies them afresh. */
  fun discard(context: Context) {
    root(context).deleteRecursively()
  }

  private fun removeOtherVersions(context: Context) {
    context.filesDir.listFiles()?.forEach {
      if (it.isDirectory && it.name.startsWith(DIR_PREFIX) && it != root(context)) it.deleteRecursively()
    }
  }

  private fun copyDir(context: Context, assetDir: String, target: File) {
    val names = context.assets.list(assetDir) ?: emptyArray()
    for (name in names) {
      val assetPath = "$assetDir/$name"
      if (name.endsWith(".bin")) {
        val out = File(target, name.removeSuffix(".bin"))
        out.parentFile?.mkdirs()
        context.assets.open(assetPath).use { input -> out.outputStream().use { input.copyTo(it, 1 shl 20) } }
      } else {
        File(target, name).mkdirs()
        copyDir(context, assetPath, File(target, name))
      }
    }
  }
}
