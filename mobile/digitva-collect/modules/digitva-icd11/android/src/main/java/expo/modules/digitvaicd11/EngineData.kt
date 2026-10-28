package expo.modules.digitvaicd11

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException

/**
 * Engine data shipped as APK assets under digitva-icd11/, each file stored as "<name>.bin" (AAPT expands ".gz"
 * assets, and the engine needs the original names). Copied into filesDir/icd11-<DATA_VERSION>/{bundle,data}; the engine
 * then writes its own derived files (unzipped index, annex, DORIS log) next to them. Those are never tracked here.
 *
 * WHO-supplied files are listed in assets digitva-icd11/who-files.json (written by stage-engine.js with size and
 * sha256). These are size-checked at start-up and restored from the APK when they are missing or the wrong size.
 *
 * The setup record is filesDir/icd11-<DATA_VERSION>.setup.json, beside the versioned dir rather than inside it, so
 * discarding a failed engine's data keeps the record. Its "state" is "attempt" (a setup started and did not finish)
 * or "shipped" (the packaged WHO files are current). No record means a fresh install or a data reset.
 */
internal object EngineData {
  /** Bump when the staged data changes: a new version dir is copied and older ones are deleted. */
  const val DATA_VERSION = "2026-01-17-doris-1.2.0-v4"
  private const val ASSET_ROOT = "digitva-icd11"
  private const val DIR_PREFIX = "icd11-"
  private const val DONE_MARKER = ".copied"
  private const val SHIPPED_MANIFEST = "who-files.json"

  /** A packaged WHO file's expected size in bytes. */
  class WhoFile(val size: Long)

  /**
   * Paths [repair] restored from the packaged copies because they were missing or the wrong size.
   */
  class Repair(val repaired: List<String>)

  fun root(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION")

  private fun setupFile(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION.setup.json")

  private fun refreshFile(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION.refresh")

  /**
   * Copies the assets if this version is not complete yet. The copy goes to a ".partial" dir that is renamed into place
   * when complete, so a process killed mid-copy leaves no half-copied root. [onPercent] gets the copy progress (0-100).
   * Throws on any I/O failure.
   */
  fun ensureCopied(context: Context, onPercent: (Int) -> Unit = {}): File {
    val root = root(context)
    if (File(root, DONE_MARKER).exists()) return root
    removeOtherVersions(context)
    val partial = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION.partial")
    partial.deleteRecursively()
    partial.mkdirs()
    val total = countAssets(context, ASSET_ROOT)
    var done = 0
    copyDir(context, ASSET_ROOT, partial, partial) {
      done++
      if (total > 0) onPercent(done * 100 / total)
    }
    File(partial, DONE_MARKER).writeText(DATA_VERSION)
    root.deleteRecursively()
    if (!partial.renameTo(root)) throw IOException("engine data rename failed")
    return root
  }

  /** Forget this version's files (including engine-derived ones) so the next init copies them afresh. The record stays. */
  fun discard(context: Context) {
    root(context).deleteRecursively()
  }

  /**
   * The setup record, or null only on a fresh install or after a data reset. A record that exists but cannot be read is
   * an interrupted setup ("attempt"), so the next init recopies the packaged data before setup.
   */
  fun setupRecord(context: Context): JSONObject? {
    val file = setupFile(context)
    if (!file.exists()) return null
    return try {
      JSONObject(file.readText())
    } catch (_: Exception) {
      JSONObject().put("state", "attempt")
    }
  }

  /** Written before setup runs: if the process dies in there, the record still says "attempt". */
  fun markAttempt(context: Context) {
    writeAtomic(setupFile(context), JSONObject().put("state", "attempt").toString())
  }

  /**
   * Records that setup completed with the packaged WHO files.
   */
  fun writeRecord(context: Context) {
    writeAtomic(setupFile(context), JSONObject().put("state", "shipped").put("files", JSONArray()).toString())
  }

  /** The shipped WHO files and expected sizes from the APK's manifest. Throws if the build has none. */
  fun shippedWho(context: Context): Map<String, WhoFile> {
    val text = context.assets.open("$ASSET_ROOT/$SHIPPED_MANIFEST").bufferedReader().use { it.readText() }
    return parse(JSONArray(text))
  }

  /**
   * A missing or wrong-size WHO file gets its packaged copy back.
   */
  fun repair(context: Context, root: File, shipped: Map<String, WhoFile>): Repair {
    val repaired = mutableListOf<String>()
    for (path in shipped.keys) {
      val expected = shipped.getValue(path)
      val file = File(root, path)
      if (file.isFile && file.length() == expected.size) continue
      repaired.add(path)
      copyAsset(context, "$ASSET_ROOT/$path.bin", file, root)
    }
    return Repair(repaired)
  }

  /** The setup summary the bridge and the check show: {"mode", "files":[{"path","size"}]}. */
  fun summary(mode: String, files: Map<String, WhoFile>): String {
    val listed = JSONArray()
    for ((path, file) in files) listed.put(JSONObject().put("path", path).put("size", file.size))
    return JSONObject().put("mode", mode).put("files", listed).toString()
  }

  /** Clears any stale refresh marker left by an older app version. */
  fun takeRefresh(context: Context): Boolean = refreshFile(context).delete()

  private fun parse(listed: JSONArray): Map<String, WhoFile> =
    (0 until listed.length()).associate { i ->
      val file = listed.getJSONObject(i)
      file.getString("path") to WhoFile(file.getLong("size"))
    }

  /** Other data versions and their setup records. The current version's record is kept. */
  private fun removeOtherVersions(context: Context) {
    val keep = setOf(root(context).name, setupFile(context).name)
    context.filesDir.listFiles()?.forEach {
      if (it.name.startsWith(DIR_PREFIX) && it.name !in keep) it.deleteRecursively()
    }
  }

  /** Writes [text] to a ".tmp" sibling and renames it over [file], so a killed write never leaves half a file. */
  private fun writeAtomic(file: File, text: String) {
    val tmp = File(file.parentFile, "${file.name}.tmp")
    tmp.writeText(text)
    if (!tmp.renameTo(file)) {
      tmp.delete()
      throw IOException("engine data rename failed")
    }
  }

  private fun countAssets(context: Context, assetDir: String): Int =
    (context.assets.list(assetDir) ?: emptyArray()).sumOf { name ->
      if (name.endsWith(".bin")) 1 else countAssets(context, "$assetDir/$name")
    }

  /** Copies the assets under [assetDir] into [target]; [engineDir] is the data dir that [target] belongs to. */
  private fun copyDir(context: Context, assetDir: String, target: File, engineDir: File, onFile: () -> Unit) {
    val names = context.assets.list(assetDir) ?: emptyArray()
    for (name in names) {
      val assetPath = "$assetDir/$name"
      if (name.endsWith(".bin")) {
        copyAsset(context, assetPath, File(target, name.removeSuffix(".bin")), engineDir)
        onFile()
      } else {
        File(target, name).mkdirs()
        copyDir(context, assetPath, File(target, name), engineDir, onFile)
      }
    }
  }

  /**
   * Writes one asset to [out] through a ".tmp" file that is renamed into place. A directory in the way is removed only
   * when it lies inside [engineDir] (our own data); anywhere else it is an error, so a bad path never deletes elsewhere.
   */
  private fun copyAsset(context: Context, assetPath: String, out: File, engineDir: File) {
    if (out.isDirectory) {
      if (!out.canonicalPath.startsWith(engineDir.canonicalPath + File.separator)) {
        throw IOException("engine data path is a directory outside the engine data")
      }
      out.deleteRecursively()
    }
    out.parentFile?.mkdirs()
    val tmp = File(out.parentFile, "${out.name}.tmp")
    context.assets.open(assetPath).use { input -> tmp.outputStream().use { input.copyTo(it, 1 shl 20) } }
    if (!tmp.renameTo(out)) {
      tmp.delete()
      throw IOException("engine data rename failed")
    }
  }
}
