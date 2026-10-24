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
 * then writes its own derived files (unzipped index, annex, DORIS log) next to them. Those are never tracked here.
 *
 * WHO-supplied files are the ones the engine's loaders fetch from WHO: the shipped files listed in assets
 * digitva-icd11/who-files.json (written by stage-engine.js with size and sha256), plus DOWNLOADED_ONLY, which ships
 * nowhere and exists only after a fetch. Only these are size-checked at start-up, restored when they are missing or
 * the wrong size, and recorded after a fetch.
 *
 * The setup record is filesDir/icd11-<DATA_VERSION>.setup.json, beside the versioned dir rather than inside it, so
 * discarding a failed engine's data keeps the record. Its "state" is "attempt" (a setup started and did not finish),
 * "downloaded" (its "files" are the WHO files that differ from the shipped copies, with size and sha256) or "shipped"
 * (no WHO file differs). No record means a fresh install or a data reset.
 */
internal object EngineData {
  /** Bump when the staged data changes: a new version dir is copied and older ones are deleted. */
  const val DATA_VERSION = "2026-01-17-doris-1.2.0-v3"
  private const val ASSET_ROOT = "digitva-icd11"
  private const val DIR_PREFIX = "icd11-"
  private const val DONE_MARKER = ".copied"
  private const val SHIPPED_MANIFEST = "who-files.json"

  /** WHO files the engine downloads that no build ships (DORIS's own zip). Tracked only once a fetch stored one. */
  private val DOWNLOADED_ONLY = listOf("data/DORIS_v2.1_1.2.0/DORIS_v2.1_1.2.0.zip")

  /** A WHO file as recorded: its size in bytes and sha256 in lowercase hex. */
  class WhoFile(val size: Long, val sha256: String)

  /**
   * Outcome of [repair]: [accepted] are the downloads still standing (repaired paths removed), [repaired] the paths
   * that were missing or the wrong size.
   */
  class Repair(val accepted: Map<String, WhoFile>, val repaired: List<String>)

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
   * an interrupted setup ("attempt"), so the next init starts from shipped copies and never fetches as a first setup.
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

  /** Written before a setup or fetch runs: if the process dies in there, the record still says "attempt". */
  fun markAttempt(context: Context) {
    writeAtomic(setupFile(context), JSONObject().put("state", "attempt").toString())
  }

  /**
   * Records a finished setup. [accepted] are the WHO files that differ from the shipped copies; none means the shipped
   * copies are the current ones.
   */
  fun writeRecord(context: Context, accepted: Map<String, WhoFile>) {
    val state = if (accepted.isEmpty()) "shipped" else "downloaded"
    writeAtomic(setupFile(context), JSONObject().put("state", state).put("files", toJson(accepted)).toString())
  }

  /** The downloads the record accepts, or none. An "attempt" record accepts nothing. */
  fun acceptedWho(record: JSONObject?): Map<String, WhoFile> =
    record?.optJSONArray("files")?.let { parse(it) } ?: emptyMap()

  /** The shipped WHO files with size and sha256, from the APK's manifest. Throws if the build has none. */
  fun shippedWho(context: Context): Map<String, WhoFile> {
    val text = context.assets.open("$ASSET_ROOT/$SHIPPED_MANIFEST").bufferedReader().use { it.readText() }
    return parse(JSONArray(text))
  }

  /** Every WHO path this build can have: the shipped ones and the downloads that ship nowhere. */
  fun whoPaths(shipped: Map<String, WhoFile>): List<String> = (shipped.keys + DOWNLOADED_ONLY).distinct()

  /**
   * Size check of each expected WHO file (the accepted download if any, else the shipped copy). A missing or wrong-size
   * file gets its shipped copy back; one with no shipped copy is removed, so the next fetch can supply it. Sizes only:
   * a sha256 pass over ~48 MB on every start is avoidable cost, and a fetch hashes what it stores anyway.
   */
  fun repair(context: Context, root: File, accepted: Map<String, WhoFile>, shipped: Map<String, WhoFile>): Repair {
    val kept = accepted.toMutableMap()
    val repaired = mutableListOf<String>()
    for (path in whoPaths(shipped)) {
      val expected = accepted[path] ?: shipped[path] ?: continue
      val file = File(root, path)
      if (file.isFile && file.length() == expected.size) continue
      repaired.add(path)
      kept.remove(path)
      if (shipped.containsKey(path)) {
        copyAsset(context, "$ASSET_ROOT/$path.bin", file, root)
      } else {
        file.delete()
      }
    }
    return Repair(kept, repaired)
  }

  /** Size and sha256 of each WHO path that is on disk now. Hashes what is present: call it after a fetch only. */
  fun currentWho(root: File, paths: List<String>): Map<String, WhoFile> =
    paths.mapNotNull { path ->
      val file = File(root, path)
      if (file.isFile) path to WhoFile(file.length(), sha256(file)) else null
    }.toMap()

  /** The setup summary the bridge and the check show: {"mode", "files":[{"path","size"}]}. */
  fun summary(mode: String, files: Map<String, WhoFile>): String {
    val listed = JSONArray()
    for ((path, file) in files) listed.put(JSONObject().put("path", path).put("size", file.size))
    return JSONObject().put("mode", mode).put("files", listed).toString()
  }

  /** Summary of the accepted downloads as they stand: "downloaded" if any, else "shipped". */
  fun summaryOf(accepted: Map<String, WhoFile>): String =
    summary(if (accepted.isEmpty()) "shipped" else "downloaded", accepted)

  /** Asks the next init, in a new engine process, to fetch WHO files. False if the request cannot be written. */
  fun requestRefresh(context: Context): Boolean =
    try {
      refreshFile(context).writeText("")
      true
    } catch (_: IOException) {
      false
    }

  /** True once after [requestRefresh]: the flag is consumed by the init that reads it. */
  fun takeRefresh(context: Context): Boolean = refreshFile(context).delete()

  private fun parse(listed: JSONArray): Map<String, WhoFile> =
    (0 until listed.length()).associate { i ->
      val file = listed.getJSONObject(i)
      file.getString("path") to WhoFile(file.getLong("size"), file.getString("sha256"))
    }

  private fun toJson(files: Map<String, WhoFile>): JSONArray {
    val listed = JSONArray()
    for ((path, file) in files) {
      listed.put(JSONObject().put("path", path).put("size", file.size).put("sha256", file.sha256))
    }
    return listed
  }

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
