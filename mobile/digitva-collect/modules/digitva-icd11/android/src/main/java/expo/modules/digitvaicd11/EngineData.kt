package expo.modules.digitvaicd11

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.security.MessageDigest

/**
 * Engine data shipped as APK assets under digitva-icd11/, each file stored as "<name>.bin" (AAPT expands ".gz"
 * assets, and the engine needs the original names). Copied into filesDir/icd11-<DATA_VERSION>/{bundle,data}; the engine
 * then writes its own derived files (unzipped index, annex) next to them.
 *
 * The first-setup record is filesDir/icd11-<DATA_VERSION>.setup.json, beside the versioned dir rather than inside it,
 * so discarding a failed engine's data keeps the record. Its "state" is "attempt" (a first setup started and did not
 * finish), "downloaded" (the setup init ran with network; "files" are what it changed or added, with sha256) or
 * "shipped" (the setup used only the shipped copies). No record means a fresh install or a data reset.
 */
internal object EngineData {
  /** Bump when the staged data changes: a new version dir is copied and older ones are deleted. */
  const val DATA_VERSION = "2026-01-17-doris-1.2.0-v2"
  private const val ASSET_ROOT = "digitva-icd11"
  private const val DIR_PREFIX = "icd11-"
  private const val DONE_MARKER = ".copied"

  /** Files this module writes itself; they never belong in a setup manifest. */
  private val OWN_FILES = setOf(DONE_MARKER, "init-timings.txt")

  fun root(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION")

  private fun setupFile(context: Context): File = File(context.filesDir, "$DIR_PREFIX$DATA_VERSION.setup.json")

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
    copyDir(context, ASSET_ROOT, partial) {
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

  /** The first-setup record, or null on a fresh install, after a data reset, or when the record cannot be read. */
  fun setupRecord(context: Context): JSONObject? =
    try {
      JSONObject(setupFile(context).readText())
    } catch (_: Exception) {
      null
    }

  /** Written before the engine runs a first setup: if the process dies in there, the record still says "attempt". */
  fun markAttempt(context: Context) {
    setupFile(context).writeText(JSONObject().put("state", "attempt").toString())
  }

  /** Records a finished setup. The [changed] files (what the setup init changed or added) are hashed here. */
  fun writeSetup(context: Context, root: File, state: String, changed: List<File>) {
    val files = JSONArray()
    for (file in changed) {
      files.put(JSONObject().put("path", file.relativeTo(root).path).put("size", file.length()).put("sha256", sha256(file)))
    }
    setupFile(context).writeText(JSONObject().put("state", state).put("files", files).toString())
  }

  /** The record without hashes, as the bridge and the engine check show it: {"mode", "files":[{"path","size"}]}. */
  fun setupSummary(record: JSONObject): String {
    val files = JSONArray()
    val listed = record.optJSONArray("files") ?: JSONArray()
    for (i in 0 until listed.length()) {
      val file = listed.getJSONObject(i)
      files.put(JSONObject().put("path", file.getString("path")).put("size", file.getLong("size")))
    }
    return JSONObject().put("mode", record.getString("state")).put("files", files).toString()
  }

  /** Size and mtime of each engine file under [root], taken before an init so the init's changes can be found. */
  fun snapshot(root: File): Map<String, String> = engineFiles(root).associate { it.relativeTo(root).path to stamp(it) }

  fun changedSince(root: File, before: Map<String, String>): List<File> =
    engineFiles(root).filter { before[it.relativeTo(root).path] != stamp(it) }.toList()

  private fun engineFiles(root: File) = root.walkTopDown().filter { it.isFile && it.name !in OWN_FILES }

  private fun stamp(file: File) = "${file.length()}:${file.lastModified()}"

  private fun sha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input ->
      val buffer = ByteArray(1 shl 16)
      while (true) {
        val read = input.read(buffer)
        if (read < 0) break
        digest.update(buffer, 0, read)
      }
    }
    return digest.digest().joinToString("") { "%02x".format(it) }
  }

  /** Other data versions and their setup records. The current version's record is kept. */
  private fun removeOtherVersions(context: Context) {
    val keep = setOf(root(context).name, setupFile(context).name)
    context.filesDir.listFiles()?.forEach {
      if (it.name.startsWith(DIR_PREFIX) && it.name !in keep) it.deleteRecursively()
    }
  }

  private fun countAssets(context: Context, assetDir: String): Int =
    (context.assets.list(assetDir) ?: emptyArray()).sumOf { name ->
      if (name.endsWith(".bin")) 1 else countAssets(context, "$assetDir/$name")
    }

  private fun copyDir(context: Context, assetDir: String, target: File, onFile: () -> Unit) {
    val names = context.assets.list(assetDir) ?: emptyArray()
    for (name in names) {
      val assetPath = "$assetDir/$name"
      if (name.endsWith(".bin")) {
        val out = File(target, name.removeSuffix(".bin"))
        out.parentFile?.mkdirs()
        context.assets.open(assetPath).use { input -> out.outputStream().use { input.copyTo(it, 1 shl 20) } }
        onFile()
      } else {
        File(target, name).mkdirs()
        copyDir(context, assetPath, File(target, name), onFile)
      }
    }
  }
}
