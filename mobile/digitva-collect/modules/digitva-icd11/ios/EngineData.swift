import Foundation

/**
 * iOS twin of EngineData.kt. The engine data ships in the app bundle as the folder digitva-icd11/ (bundle/, data/,
 * who-files.json; plain names, no ".bin": that suffix is for AAPT only). The bundle is read-only and the engine writes
 * derived files (unzipped index, annex, DORIS log) next to its data, so it is copied once into
 * Application Support/icd11-<dataVersion>/{bundle,data}, excluded from iCloud backup (it is rebuilt from the app).
 *
 * WHO-supplied files are listed in who-files.json (written by stage-engine.js with size and sha256); they are
 * size-checked at every init and restored from the bundle when missing or the wrong size. The setup record
 * icd11-<dataVersion>.setup.json sits beside the versioned dir with "state" "attempt" or "shipped", as on Android.
 */
enum EngineData {
  /** Bump with EngineData.kt's DATA_VERSION when the staged data changes. */
  static let dataVersion = "2026-01-17-doris-1.2.0-v4"
  private static let assetRoot = "digitva-icd11"
  private static let dirPrefix = "icd11-"
  private static let doneMarker = ".copied"
  private static let shippedManifest = "who-files.json"
  private static let files = FileManager.default

  /** The packaged data folder in the app bundle, or nil when this build has none. */
  static func packaged() -> URL? {
    guard let url = Bundle.main.url(forResource: assetRoot, withExtension: nil),
          files.fileExists(atPath: url.appendingPathComponent(shippedManifest).path) else { return nil }
    return url
  }

  private static func base() throws -> URL {
    try files.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
  }

  static func root() throws -> URL { try base().appendingPathComponent(dirPrefix + dataVersion, isDirectory: true) }

  private static func setupFile() throws -> URL { try base().appendingPathComponent("\(dirPrefix)\(dataVersion).setup.json") }

  /**
   * Copies the packaged data if this version is not complete yet, through a ".partial" dir renamed into place, so an
   * app killed mid-copy leaves no half-copied root. [onPercent] gets the copy progress (0-100). Throws on any I/O failure.
   */
  static func ensureCopied(_ onPercent: (Int) -> Void) throws -> URL {
    let root = try root()
    if files.fileExists(atPath: root.appendingPathComponent(doneMarker).path) { return root }
    guard let source = packaged() else { throw CocoaError(.fileNoSuchFile) }
    try removeOtherVersions()
    let partial = try base().appendingPathComponent("\(dirPrefix)\(dataVersion).partial", isDirectory: true)
    try? files.removeItem(at: partial)
    try files.createDirectory(at: partial, withIntermediateDirectories: true)
    let all = try packagedFiles(source)
    for (done, rel) in all.enumerated() {
      let out = partial.appendingPathComponent(rel)
      try files.createDirectory(at: out.deletingLastPathComponent(), withIntermediateDirectories: true)
      // APFS clones the file when bundle and container share a volume, so this is fast and takes no extra space.
      try files.copyItem(at: source.appendingPathComponent(rel), to: out)
      onPercent((done + 1) * 100 / all.count)
    }
    // Excluded before the rename (the flag moves with the folder), so no root ever sits in backups unflagged.
    var noBackup = URLResourceValues()
    noBackup.isExcludedFromBackup = true
    var excluded = partial
    try excluded.setResourceValues(noBackup)
    try Data(dataVersion.utf8).write(to: partial.appendingPathComponent(doneMarker))
    try? files.removeItem(at: root)
    try files.moveItem(at: partial, to: root)
    return root
  }

  /** Forget this version's files (engine-derived ones included) so the next init copies them afresh. The record stays. */
  static func discard() {
    if let root = try? root() { try? files.removeItem(at: root) }
  }

  /** The setup record; nil only on a fresh install. A record that cannot be read counts as an interrupted setup. */
  static func setupRecord() -> [String: Any]? {
    guard let file = try? setupFile(), files.fileExists(atPath: file.path) else { return nil }
    guard let data = try? Data(contentsOf: file),
          let record = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return ["state": "attempt"] }
    return record
  }

  static func markAttempt() throws { try writeRecord(["state": "attempt"]) }

  static func writeShipped() throws { try writeRecord(["state": "shipped", "files": [Any]()]) }

  private static func writeRecord(_ record: [String: Any]) throws {
    try JSONSerialization.data(withJSONObject: record).write(to: try setupFile(), options: .atomic)
  }

  /** Shipped WHO files and their expected sizes, from the bundle's who-files.json. Throws if the build has none. */
  static func shippedWho() throws -> [String: Int64] {
    guard let source = packaged() else { throw CocoaError(.fileNoSuchFile) }
    let listed = try JSONSerialization.jsonObject(with: Data(contentsOf: source.appendingPathComponent(shippedManifest)))
    guard let entries = listed as? [[String: Any]] else { throw CocoaError(.fileReadCorruptFile) }
    var shipped: [String: Int64] = [:]
    for entry in entries {
      guard let path = entry["path"] as? String, let size = entry["size"] as? NSNumber else { throw CocoaError(.fileReadCorruptFile) }
      shipped[path] = size.int64Value
    }
    return shipped
  }

  /** A missing or wrong-size WHO file gets its packaged copy back. Returns the paths restored. */
  static func repair(_ root: URL, _ shipped: [String: Int64]) throws -> [String] {
    guard let source = packaged() else { throw CocoaError(.fileNoSuchFile) }
    var repaired: [String] = []
    for (path, size) in shipped {
      let file = root.appendingPathComponent(path).standardizedFileURL
      // Paths come from our own signed bundle; still, never write outside the engine data.
      guard file.path.hasPrefix(root.standardizedFileURL.path + "/") else { throw CocoaError(.fileWriteInvalidFileName) }
      let attributes = try? files.attributesOfItem(atPath: file.path)
      if attributes?[.type] as? FileAttributeType == .typeRegular, (attributes?[.size] as? NSNumber)?.int64Value == size { continue }
      repaired.append(path)
      try? files.removeItem(at: file)
      try files.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
      let tmp = file.appendingPathExtension("tmp")
      try? files.removeItem(at: tmp)
      try files.copyItem(at: source.appendingPathComponent(path), to: tmp)
      try files.moveItem(at: tmp, to: file)
    }
    return repaired
  }

  /** The setup summary the bridge and the check show; the same text EngineData.kt writes. */
  static let shippedSummary = "{\"mode\":\"shipped\",\"files\":[]}"

  /** The engine's files under [dir] (everything but who-files.json, which Android keeps in assets too), relative, sorted. */
  private static func packagedFiles(_ dir: URL) throws -> [String] {
    try files.subpathsOfDirectory(atPath: dir.path).filter { rel in
      var isDir: ObjCBool = false
      return rel != shippedManifest && files.fileExists(atPath: dir.appendingPathComponent(rel).path, isDirectory: &isDir) && !isDir.boolValue
    }.sorted()
  }

  /** Other data versions and their setup records; this version's record is kept. */
  private static func removeOtherVersions() throws {
    let base = try base()
    let keep: Set<String> = [try root().lastPathComponent, try setupFile().lastPathComponent]
    for name in (try? files.contentsOfDirectory(atPath: base.path)) ?? [] where name.hasPrefix(dirPrefix) && !keep.contains(name) {
      try? files.removeItem(at: base.appendingPathComponent(name))
    }
  }
}
