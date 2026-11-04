import ExpoModulesCore
import Foundation
#if DIGITVA_SMARTVA_LINKED
import SmartvaRust
#endif

/**
 * Expo bridge for the Plus-only SmartVA engine on iOS: the twin of android/.../DigitvaSmartvaModule.kt,
 * SmartvaService.kt and cpp/SmartVaJni.cpp, with the same JS API (src/smartva/nativeEngine.ts), request checks, size
 * limits and error codes.
 *
 * iOS has no separate app process, so the engine runs in the app process on one dedicated worker thread (SerialWorker):
 * calls are serialized as in the Android service, and the JS thread never blocks. A crash in the engine ends the app
 * (on Android it ends only the :smartva process). The Rust ABI catches panics (smartva-rust's `guard`), so that takes a
 * memory fault or an abort, not an engine error.
 *
 * Linking: the podspec vendors SmartvaRust.xcframework and defines DIGITVA_SMARTVA_LINKED only when the xcframework was
 * staged into this folder (Plus builds, plugins/with-ios-collect-plus.js). Without it this file compiles to a module
 * whose isAvailable() is false and whose init/score answer "unavailable", like an Android build without the library.
 *
 * Nothing here logs the request, the result or an engine error text.
 */
public final class DigitvaSmartvaModule: Module {
  static let maxRequestBytes = 1024 * 1024
  static let maxReplyBytes = 2 * 1024 * 1024

  #if DIGITVA_SMARTVA_LINKED
  static let linked = true
  #else
  static let linked = false
  #endif

  // 8 MiB: more than a JVM worker's default; the Rust engine's own threads get 2 MiB.
  private let worker = SerialWorker(name: "smartva-engine", stackSize: 8 << 20)
  // Touched only on the worker thread.
  private var initialized = false
  private var engineVersion: String?

  public func definition() -> ModuleDefinition {
    Name("DigitvaSmartva")

    AsyncFunction("isAvailable") { () -> Bool in
      return Self.linked
    }

    AsyncFunction("init") { (promise: Promise) in
      self.worker.submit { promise.resolve(self.initialize()) }
    }

    AsyncFunction("score") { (request: String, promise: Promise) in
      if request.utf8.count > Self.maxRequestBytes {
        promise.resolve(Self.failure("too_large"))
        return
      }
      self.worker.submit { promise.resolve(self.score(request)) }
    }
  }

  static func failure(_ code: String, ms: Int = 0) -> [String: Any] {
    return ["ok": false, "error": code, "ms": ms]
  }

  private static func millis(since start: DispatchTime) -> Int {
    return Int((DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000)
  }

  /// Worker thread only.
  private func initialize() -> [String: Any] {
    guard Self.linked else { return Self.failure("unavailable") }
    let start = DispatchTime.now()
    guard let version = Self.nativeVersion(), !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
      return Self.failure("native_error")
    }
    engineVersion = version
    initialized = true
    return ["ok": true, "version": version, "ms": Self.millis(since: start)]
  }

  /// Worker thread only. The checks are SmartvaService.score's, in its order.
  private func score(_ request: String) -> [String: Any] {
    if request.utf8.count > Self.maxRequestBytes { return Self.failure("too_large") }
    if !initialized {
      let result = initialize()
      if result["ok"] as? Bool != true { return result }
    }
    guard let parsed = Self.parse(request) else { return Self.failure("bad_request") }

    let start = DispatchTime.now()
    let text = Self.nativeScore(rows: parsed.rows, country: parsed.country, flags: parsed.flags)
    let duration = Self.millis(since: start)
    guard let text else { return Self.failure("native_error", ms: duration) }
    if text == "TOO_LARGE" { return Self.failure("too_large", ms: duration) }
    if text == "ENGINE_ERROR" { return Self.failure("engine_error", ms: duration) }
    if text.utf8.count > Self.maxReplyBytes { return Self.failure("too_large", ms: duration) }
    var result: [String: Any] = ["ok": true, "text": text, "ms": duration, "nativeMs": duration]
    if let engineVersion { result["version"] = engineVersion }
    return result
  }

  struct ParsedRequest {
    let rows: String
    let country: String
    /// hiv, malaria, hce, freetext
    let flags: [Bool]
  }

  /// JSONSerialization reads JSON true/false as NSNumber; this tells a real boolean from a number.
  static func isBoolean(_ value: Any?) -> Bool {
    guard let number = value as? NSNumber else { return false }
    return CFGetTypeID(number) == CFBooleanGetTypeID()
  }

  /**
   * The request {schema_version: 1, input: {name: string}, options: {country, hiv, malaria, hce, freetext}} as the
   * engine's one-row JSON array, or nil when it is not that shape (Android answers the same cases with bad_request).
   * The row is written with sorted keys: the engine builds its CSV header from key order and reads columns by name,
   * so the order does not change the result.
   */
  static func parse(_ request: String) -> ParsedRequest? {
    guard let data = request.data(using: .utf8),
          let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return nil }
    guard let schema = root["schema_version"] as? NSNumber, !isBoolean(schema), schema.intValue == 1 else { return nil }
    guard let row = root["input"] as? [String: Any], let options = root["options"] as? [String: Any] else { return nil }
    guard let country = options["country"] as? String,
          !country.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          !country.contains("\u{0}") else { return nil }
    var flags: [Bool] = []
    for key in ["hiv", "malaria", "hce", "freetext"] {
      guard isBoolean(options[key]), let value = options[key] as? Bool else { return nil }
      flags.append(value)
    }
    for (_, value) in row {
      guard let text = value as? String, !text.contains("\u{0}") else { return nil }
    }
    guard let rows = try? JSONSerialization.data(withJSONObject: [row], options: [.sortedKeys]),
          let rowsText = String(data: rows, encoding: .utf8) else { return nil }
    return ParsedRequest(rows: rowsText, country: country, flags: flags)
  }

  private static func nativeVersion() -> String? {
    #if DIGITVA_SMARTVA_LINKED
    guard let pointer = smartva_version() else { return nil }
    return String(cString: pointer)
    #else
    return nil
    #endif
  }

  /// cpp/SmartVaJni.cpp's scoreJson: the result text, or the status words "TOO_LARGE" / "ENGINE_ERROR", or nil.
  private static func nativeScore(rows: String, country: String, flags: [Bool]) -> String? {
    #if DIGITVA_SMARTVA_LINKED
    if rows.utf8.count > maxRequestBytes || rows.isEmpty || country.isEmpty { return "TOO_LARGE" }
    var result: UnsafeMutablePointer<CChar>?
    var error: UnsafeMutablePointer<CChar>?
    let flag = { (value: Bool) -> Int32 in value ? 1 : 0 }
    let code = rows.withCString { payload in
      country.withCString { countryText in
        smartva_score_json(payload, countryText, flag(flags[0]), flag(flags[1]), flag(flags[2]), flag(flags[3]), 0, &result, &error)
      }
    }
    // The error text can echo input: freed unread.
    if let error { smartva_free_string(error) }
    guard code == 0, let result else {
      if let result { smartva_free_string(result) }
      return "ENGINE_ERROR"
    }
    defer { smartva_free_string(result) }
    if strlen(result) > maxReplyBytes { return "TOO_LARGE" }
    return String(cString: result)
    #else
    return nil
    #endif
  }
}
