import ExpoModulesCore
import Foundation
import SmartvaRust

/**
 * iOS twin of DigitvaSmartvaModule.kt + SmartvaService.kt + SmartVaJni.cpp: the same functions, request checks, limits
 * and result maps, so src/smartva/nativeEngine.ts has no platform branch. The Rust library is linked statically, so
 * isAvailable is always true and "unavailable" never comes back. Scoring runs serially on one worker thread inside the
 * app (iOS has no second process): ERR_SMARTVA_PROCESS never fires. Requests and results are never logged.
 */
public class DigitvaSmartvaModule: Module {
  private static let maxRequestBytes = 1024 * 1024
  private static let maxReplyBytes = 2 * 1024 * 1024
  private let queue = SmartvaWorker()
  // Touched only on [queue].
  private var engineVersion: String?

  public func definition() -> ModuleDefinition {
    Name("DigitvaSmartva")

    AsyncFunction("isAvailable") { () -> Bool in true }

    // The engine runs in-process and cannot unload: nothing to stop (Android ends its process, digitva-xhz7).
    AsyncFunction("release") { () -> Bool in true }

    AsyncFunction("init") { (promise: Promise) in
      self.queue.submit { promise.resolve(self.initialize()) }
    }

    AsyncFunction("score") { (request: String, promise: Promise) in
      if request.utf8.count > Self.maxRequestBytes { return promise.resolve(Self.failure("too_large")) }
      self.queue.submit { promise.resolve(self.score(request)) }
    }
  }

  private static func failure(_ code: String, ms: Int = 0) -> [String: Any] { ["ok": false, "error": code, "ms": ms] }

  private static func millis(since start: DispatchTime) -> Int {
    Int((DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000)
  }

  private func initialize() -> [String: Any] {
    let start = DispatchTime.now()
    guard let raw = smartva_version() else { return Self.failure("native_error") }
    let version = String(cString: raw)
    if version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return Self.failure("native_error") }
    engineVersion = version
    return ["ok": true, "version": version, "ms": Self.millis(since: start)]
  }

  private static func isBool(_ value: Any?) -> Bool {
    guard let number = value as? NSNumber else { return false }
    return CFGetTypeID(number) == CFBooleanGetTypeID()
  }

  /**
   * The checks of SmartvaService.score: {schema_version: 1, input: {<name>: <string>}, options: {country, hiv, malaria,
   * hce, freetext}}; anything else is bad_request. Returns the single-row payload, the country and the four flags.
   */
  private static func parse(_ request: String) -> (rows: String, country: String, flags: [Int32])? {
    guard let root = (try? JSONSerialization.jsonObject(with: Data(request.utf8))) as? [String: Any],
          let schema = root["schema_version"] as? NSNumber, !isBool(schema), schema.intValue == 1,
          let row = root["input"] as? [String: Any], let options = root["options"] as? [String: Any],
          let country = options["country"] as? String,
          !country.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, !country.contains("\u{0}") else { return nil }
    var flags: [Int32] = []
    for key in ["hiv", "malaria", "hce", "freetext"] {
      guard isBool(options[key]), let flag = options[key] as? Bool else { return nil }
      flags.append(flag ? 1 : 0)
    }
    for value in row.values {
      guard let text = value as? String, !text.contains("\u{0}") else { return nil }
    }
    guard let rows = try? JSONSerialization.data(withJSONObject: [row]), let text = String(data: rows, encoding: .utf8) else { return nil }
    return (text, country, flags)
  }

  private func score(_ request: String) -> [String: Any] {
    if engineVersion == nil {
      let started = initialize()
      if started["ok"] as? Bool != true { return started }
    }
    guard let parsed = Self.parse(request) else { return Self.failure("bad_request") }
    if parsed.rows.utf8.count > Self.maxRequestBytes { return Self.failure("too_large") }
    let start = DispatchTime.now()
    var result: UnsafeMutablePointer<CChar>?
    var error: UnsafeMutablePointer<CChar>?
    let flags = parsed.flags
    let code = smartva_score_json(parsed.rows, parsed.country, flags[0], flags[1], flags[2], flags[3], 0, &result, &error)
    let ms = Self.millis(since: start)
    if let error { smartva_free_string(error) }
    guard code == 0, let result else {
      if let result { smartva_free_string(result) }
      return Self.failure("engine_error", ms: ms)
    }
    defer { smartva_free_string(result) }
    if strlen(result) > Self.maxReplyBytes { return Self.failure("too_large", ms: ms) }
    return ["ok": true, "text": String(cString: result), "ms": ms, "nativeMs": ms, "version": engineVersion as Any]
  }
}

/**
 * The one scoring thread, jobs first come first served. A Dispatch queue thread has a 512 KB stack, below Android's
 * worker; this thread gets 8 MB, the main thread's size the 8,399-case parity run scored on, so a deep scoring path
 * cannot overflow it.
 */
final class SmartvaWorker {
  private let condition = NSCondition()
  private var jobs: [() -> Void] = []
  private var thread: Thread?

  func submit(_ job: @escaping () -> Void) {
    condition.lock()
    jobs.append(job)
    if thread == nil {
      let worker = Thread { [unowned self] in self.run() }
      worker.name = "smartva-engine"
      worker.stackSize = 8 << 20
      worker.qualityOfService = .userInitiated
      thread = worker
      worker.start()
    }
    condition.signal()
    condition.unlock()
  }

  private func run() {
    while true {
      condition.lock()
      while jobs.isEmpty { condition.wait() }
      let job = jobs.removeFirst()
      condition.unlock()
      job()
    }
  }
}
