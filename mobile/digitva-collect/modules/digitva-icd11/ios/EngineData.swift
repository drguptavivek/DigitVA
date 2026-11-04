import Foundation

/**
 * The iOS twin of android/.../EngineData.kt. The engine data ships in the pod's resource bundle DigitvaIcd11Data.bundle,
 * folder Icd11Data/ (the bundle/ and data/ trees and who-files.json; staged by scripts/stage-engine.js stageIcd11Ios under the
 * original names: an app bundle does not expand .gz files the way AAPT does, so there is no ".bin" suffix). It is copied
 * into Application Support/digitva-icd11/icd11-<DATA_VERSION>/{bundle,data}; the engine then writes its own derived
 * files (unzipped index, annex, DORIS log, init-timings.txt) next to them. Those are never tracked here.
 *
 * Application Support/digitva-icd11 is excluded from iCloud and device backups (the data is reproducible from the app)
 * and created with NSFileProtectionCompleteUntilFirstUserAuthentication, which new files inside inherit: the engine may
 * start while the device is locked after the first unlock, never before it.
 *
 * The setup record is icd11-<DATA_VERSION>.setup.json beside the versioned dir, "attempt" or "shipped", as on Android.
 * All of it runs on the engine worker thread only.
 */
enum EngineData {
  /// Bump with EngineData.kt's DATA_VERSION: a new version dir is copied and older ones are deleted.
  static let dataVersion = "2026-01-17-doris-1.2.0-v4"
  static let resourceBundle = "DigitvaIcd11Data"
  static let resourceFolder = "Icd11Data"
  private static let dirPrefix = "icd11-"
  private static let doneMarker = ".copied"
  private static let shippedManifest = "who-files.json"

  struct EngineDataError: Error {
    let code: String
  }

  private static var fileManager: FileManager { FileManager.default }

  /// The packaged data folder inside the app, or nil when this build has none.
  static func packagedRoot() -> URL? {
    let candidates = [Bundle.main] + Bundle.allBundles + [Bundle(for: BundleToken.self)]
    for bundle in candidates {
      if let url = bundle.url(forResource: resourceBundle, withExtension: "bundle"),
         let resources = Bundle(url: url),
         let folder = resources.resourceURL?.appendingPathComponent(resourceFolder, isDirectory: true),
         fileManager.fileExists(atPath: folder.appendingPathComponent(shippedManifest).path) {
        return folder
      }
    }
    return nil
  }

  private final class BundleToken {}

  /// Application Support/digitva-icd11, created with its protection class and excluded from backup.
  static func baseDir() throws -> URL {
    let support = try fileManager.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
    var base = support.appendingPathComponent("digitva-icd11", isDirectory: true)
    if !fileManager.fileExists(atPath: base.path) {
      try fileManager.createDirectory(at: base, withIntermediateDirectories: true,
                                      attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
    }
    var values = URLResourceValues()
    values.isExcludedFromBackup = true
    try base.setResourceValues(values)
    return base
  }

  static func root() throws -> URL { try baseDir().appendingPathComponent("\(dirPrefix)\(dataVersion)", isDirectory: true) }
  private static func setupFile() throws -> URL { try baseDir().appendingPathComponent("\(dirPrefix)\(dataVersion).setup.json") }
  private static func refreshFile() throws -> URL { try baseDir().appendingPathComponent("\(dirPrefix)\(dataVersion).refresh") }

  /**
   * Copies the packaged data if this version is not complete yet, into a ".partial" dir that is renamed into place when
   * complete, so an app killed mid-copy leaves no half-copied root. [onPercent] gets the copy progress (0-100).
   */
  static func ensureCopied(onPercent: (Int) -> Void) throws -> URL {
    let root = try root()
    if fileManager.fileExists(atPath: root.appendingPathComponent(doneMarker).path) { return root }
    guard let packaged = packagedRoot() else { throw EngineDataError(code: "no_packaged_data") }
    try removeOtherVersions()
    let partial = try baseDir().appendingPathComponent("\(dirPrefix)\(dataVersion).partial", isDirectory: true)
    try? fileManager.removeItem(at: partial)
    try fileManager.createDirectory(at: partial, withIntermediateDirectories: true)
    let files = try packagedFiles(packaged)
    var done = 0
    for relative in files {
      try copyFile(from: packaged.appendingPathComponent(relative), to: partial.appendingPathComponent(relative), engineDir: partial)
      done += 1
      if !files.isEmpty { onPercent(done * 100 / files.count) }
    }
    try Data(dataVersion.utf8).write(to: partial.appendingPathComponent(doneMarker))
    try? fileManager.removeItem(at: root)
    try fileManager.moveItem(at: partial, to: root)
    return root
  }

  /// Forget this version's files (including engine-derived ones) so the next init copies them afresh. The record stays.
  static func discard() {
    if let root = try? root() { try? fileManager.removeItem(at: root) }
  }

  /// The setup record, or nil on a fresh install or after a data reset. An unreadable record counts as "attempt".
  static func setupRecord() -> [String: Any]? {
    guard let file = try? setupFile(), fileManager.fileExists(atPath: file.path) else { return nil }
    guard let data = try? Data(contentsOf: file),
          let record = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return ["state": "attempt"] }
    return record
  }

  /// Written before setup runs: if the app dies in there, the record still says "attempt".
  static func markAttempt() throws {
    try writeAtomic(try setupFile(), ["state": "attempt"])
  }

  /// Records that setup completed with the packaged WHO files.
  static func writeRecord() throws {
    try writeAtomic(try setupFile(), ["state": "shipped", "files": [Any]()])
  }

  /// The shipped WHO files and expected sizes from who-files.json. Throws if the build has none.
  static func shippedWho() throws -> [(path: String, size: Int64)] {
    guard let packaged = packagedRoot() else { throw EngineDataError(code: "no_packaged_data") }
    let data = try Data(contentsOf: packaged.appendingPathComponent(shippedManifest))
    guard let listed = (try JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else {
      throw EngineDataError(code: "bad_manifest")
    }
    return try listed.map { file in
      guard let path = file["path"] as? String, let size = (file["size"] as? NSNumber)?.int64Value else {
        throw EngineDataError(code: "bad_manifest")
      }
      return (path, size)
    }
  }

  /// A missing or wrong-size WHO file gets its packaged copy back. Returns the paths it restored.
  @discardableResult
  static func repair(root: URL, shipped: [(path: String, size: Int64)]) throws -> [String] {
    guard let packaged = packagedRoot() else { throw EngineDataError(code: "no_packaged_data") }
    var repaired: [String] = []
    for file in shipped {
      let target = root.appendingPathComponent(file.path)
      var isDirectory: ObjCBool = false
      if fileManager.fileExists(atPath: target.path, isDirectory: &isDirectory), !isDirectory.boolValue,
         let size = (try? fileManager.attributesOfItem(atPath: target.path))?[.size] as? NSNumber,
         size.int64Value == file.size {
        continue
      }
      repaired.append(file.path)
      try copyFile(from: packaged.appendingPathComponent(file.path), to: target, engineDir: root)
    }
    return repaired
  }

  /// The setup summary the bridge and the check show: {"mode", "files":[{"path","size"}]}.
  static func summary(mode: String, files: [(path: String, size: Int64)]) -> String {
    let listed = files.map { ["path": $0.path, "size": $0.size] as [String: Any] }
    let object: [String: Any] = ["mode": mode, "files": listed]
    guard let data = try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]) else { return "{}" }
    return String(decoding: data, as: UTF8.self)
  }

  /// Clears any stale refresh marker. True when one was there.
  @discardableResult
  static func takeRefresh() -> Bool {
    guard let file = try? refreshFile() else { return false }
    return (try? fileManager.removeItem(at: file)) != nil
  }

  /// Every regular file under [packaged] except the manifest, as sorted relative paths.
  private static func packagedFiles(_ packaged: URL) throws -> [String] {
    guard let walker = fileManager.enumerator(at: packaged, includingPropertiesForKeys: [.isRegularFileKey]) else { return [] }
    let base = packaged.standardizedFileURL.path
    var files: [String] = []
    for case let url as URL in walker {
      guard (try url.resourceValues(forKeys: [.isRegularFileKey])).isRegularFile == true else { continue }
      let full = url.standardizedFileURL.path
      guard full.hasPrefix(base + "/") else { continue }
      let relative = String(full.dropFirst(base.count + 1))
      if relative != shippedManifest { files.append(relative) }
    }
    return files.sorted()
  }

  /// Other data versions and their setup records. The current version's record is kept.
  private static func removeOtherVersions() throws {
    let base = try baseDir()
    let keep: Set<String> = ["\(dirPrefix)\(dataVersion)", "\(dirPrefix)\(dataVersion).setup.json"]
    for name in (try? fileManager.contentsOfDirectory(atPath: base.path)) ?? [] where name.hasPrefix(dirPrefix) && !keep.contains(name) {
      try? fileManager.removeItem(at: base.appendingPathComponent(name))
    }
  }

  private static func writeAtomic(_ file: URL, _ object: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: object)
    try data.write(to: file, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
  }

  /**
   * Copies one file through a ".tmp" sibling renamed into place. A directory in the way is removed only when it lies
   * inside [engineDir] (our own data); anywhere else it is an error, so a bad path never deletes elsewhere.
   */
  private static func copyFile(from source: URL, to target: URL, engineDir: URL) throws {
    var isDirectory: ObjCBool = false
    if fileManager.fileExists(atPath: target.path, isDirectory: &isDirectory), isDirectory.boolValue {
      let inside = target.standardizedFileURL.resolvingSymlinksInPath().path
      let engine = engineDir.standardizedFileURL.resolvingSymlinksInPath().path
      guard inside.hasPrefix(engine + "/") else { throw EngineDataError(code: "path_outside_engine_data") }
      try fileManager.removeItem(at: target)
    }
    try fileManager.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
    let tmp = target.deletingLastPathComponent().appendingPathComponent(target.lastPathComponent + ".tmp")
    try? fileManager.removeItem(at: tmp)
    try fileManager.copyItem(at: source, to: tmp)
    if fileManager.fileExists(atPath: target.path) { try fileManager.removeItem(at: target) }
    try fileManager.moveItem(at: tmp, to: target)
  }
}
