import ExpoModulesCore
import Foundation
#if DIGITVA_ICD11_LINKED
import DigitvaIcd11Engine
#endif

/**
 * JS face of the offline WHO ICD-11 / DORIS engine on iOS: the twin of android/.../DigitvaIcd11Module.kt, EngineHost.kt
 * and Icd11Service.kt, with the same API (src/offlineEngine.ts NativeEngine), result maps and error codes.
 *
 * iOS has no separate app process. The engine (DigitvaIcd11Engine.xcframework, engine-src/build-ios.sh) is linked into
 * the app and runs on one dedicated worker thread with a 32 MiB stack (NativeAOT start-up is stack hungry), which
 * serializes init and calls as the Android service's worker does; the JS thread never blocks. Consequences the Android
 * build does not have: an engine crash ends the app, and the engine's resident set (about 600 MB on Android) counts
 * against the app's own memory limit. Init happens once per app run and a failed init is sticky until the app restarts.
 *
 * Engine error payloads can hold stack traces and certificate text: they are neither logged nor returned; JS gets a
 * status or a short code. Progress reports become the "icd11Progress" event ({ phase, percent }, percent -1 when
 * unknown). updateWhoFiles is kept for API compatibility and answers bundled_only, as Android's service does.
 *
 * Linking: the podspec vendors the engine and defines DIGITVA_ICD11_LINKED only when the xcframework was staged into
 * this folder (Plus builds). Without it isAvailable() is false and init answers "unavailable".
 */
public final class DigitvaIcd11Module: Module {
  #if DIGITVA_ICD11_LINKED
  static let linked = true
  #else
  static let linked = false
  #endif

  /// Icd11Service.OP_NAME: the shape of an op name; which names exist is the bridge's business.
  static func isOpName(_ op: String) -> Bool {
    let scalars = op.unicodeScalars
    return (1...32).contains(scalars.count) && scalars.allSatisfy { ($0 >= "a" && $0 <= "z") || $0 == "_" }
  }

  private let worker = SerialWorker(name: "icd11-engine", stackSize: 32 << 20)
  private lazy var host = EngineHost { [weak self] phase, percent in
    self?.sendEvent("icd11Progress", ["phase": phase, "percent": percent])
  }

  public func definition() -> ModuleDefinition {
    Name("DigitvaIcd11")

    Events("icd11Progress")

    // Whether this build carries the engine; does not start it.
    AsyncFunction("isAvailable") { () -> Bool in
      return Self.linked && EngineData.packagedRoot() != nil
    }

    AsyncFunction("init") { (promise: Promise) in
      self.worker.submit { promise.resolve(Self.guarded { self.host.initialize() }) }
    }

    // Retained for API compatibility: WHO files are bundled only. Clears a stale refresh marker like Android's dropRefresh.
    AsyncFunction("updateWhoFiles") { (promise: Promise) in
      self.worker.submit {
        EngineData.takeRefresh()
        promise.resolve(["ok": false, "error": "bundled_only"])
      }
    }

    // `op` is the bridge's op name and `input` the JSON object of its arguments. Only the name's shape is checked here.
    AsyncFunction("call") { (op: String, input: String, promise: Promise) in
      guard Self.isOpName(op) else {
        promise.reject("ERR_ICD11_OP", "bad engine op")
        return
      }
      self.worker.submit { promise.resolve(Self.guarded { self.host.call(op: op, input: input) }) }
    }
  }

  /// Icd11Service.answerWith without Binder: the size cap on `text` is kept so both platforms answer the same way.
  static func guarded(_ work: () -> [String: Any]) -> [String: Any] {
    return EngineHost.boundReply(work())
  }
}

/**
 * The engine's lifecycle and calls (EngineHost.kt). Worker thread only. Every init runs behind a dead proxy: engine and
 * WHO data are packaged together and runtime downloads are refused.
 */
final class EngineHost {
  /// Icd11Service.MAX_TEXT_CHARS: UTF-16 units, the unit Android's cap counts.
  static let maxTextChars = 250_000
  private let progress: (String, Int) -> Void
  private var initResult: [String: Any]?

  init(progress: @escaping (String, Int) -> Void) {
    self.progress = progress
  }

  private static func millis(since start: DispatchTime) -> Double {
    return Double(DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000.0
  }

  private static func fail(_ code: String, copyMs: Double = 0, initMs: Double = 0, totalMs: Double = 0) -> [String: Any] {
    return ["ok": false, "error": code, "copyMs": copyMs, "initMs": initMs, "ms": totalMs, "cached": false]
  }

  static func boundReply(_ map: [String: Any]) -> [String: Any] {
    guard let text = map["text"] as? String, text.utf16.count > maxTextChars else { return map }
    var bounded = map
    bounded.removeValue(forKey: "text")
    bounded["ok"] = false
    bounded["error"] = "too_large"
    return bounded
  }

  func initialize() -> [String: Any] {
    if var cached = initResult {
      cached["cached"] = true
      cached["ms"] = 0.0
      return cached
    }
    let start = DispatchTime.now()
    let result = runInit(start: start)
    initResult = result
    return result
  }

  private func runInit(start: DispatchTime) -> [String: Any] {
    guard DigitvaIcd11Module.linked, EngineData.packagedRoot() != nil else { return Self.fail("unavailable") }
    do {
      let record = EngineData.setupRecord()
      // A setup that started and never finished: start from the packaged copies.
      let interrupted = (record?["state"] as? String) == "attempt"
      if interrupted { EngineData.discard() }
      let copyStart = DispatchTime.now()
      let root = try EngineData.ensureCopied { percent in self.progress("copy", percent) }
      let copyMs = Self.millis(since: copyStart)
      let data = root.appendingPathComponent("data", isDirectory: true)
      let shipped = try EngineData.shippedWho()
      let repaired = try EngineData.repair(root: root, shipped: shipped)
      Self.guardNetwork()
      let recordSetup = record == nil || interrupted
      if recordSetup { try EngineData.markAttempt() }
      progress("engine", -1)
      let initStart = DispatchTime.now()
      let ok = Self.nativeInit(bundle: root.appendingPathComponent("bundle", isDirectory: true).path, data: data.path)
      let initMs = Self.millis(since: initStart)
      guard ok else {
        // Derived files may be half written; start from clean data after a restart.
        EngineData.discard()
        return Self.fail("init_failed", copyMs: copyMs, initMs: initMs, totalMs: Self.millis(since: start))
      }
      if recordSetup || !repaired.isEmpty { try EngineData.writeRecord() }
      progress("ready", 100)
      return [
        "ok": true, "copyMs": copyMs, "initMs": initMs, "ms": Self.millis(since: start), "cached": false,
        "phases": Self.phases(root), "setup": EngineData.summary(mode: "shipped", files: []),
      ]
    } catch {
      // No message: it can carry paths or data.
      return Self.fail("data_copy_failed", totalMs: Self.millis(since: start))
    }
  }

  /**
   * The engine's DORIS and language-resource loaders try to download WHO files that are already shipped, and have no
   * setting to switch that off. A dead proxy makes each attempt fail at once and the engine falls back to the local files
   * (EngineHost.kt guardNetwork). On iOS this sets the variables for the whole app process; NSURLSession (React Native's
   * networking) does not read them. TO VERIFY on a device: that .NET's HttpClient on iOS honours them (it reads the
   * environment proxy first on Unix-like systems) and that no request leaves the app during init.
   */
  private static func guardNetwork() {
    for name in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"] { setenv(name, "http://127.0.0.1:9", 1) }
  }

  /// "config=3900 doris=12500 index=17900 ready=17901" written by the bridge; empty unless in exactly that shape.
  private static func phases(_ root: URL) -> String {
    guard let text = try? String(contentsOf: root.appendingPathComponent("init-timings.txt"), encoding: .utf8) else { return "" }
    let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
    let pattern = "^[a-z]+=[0-9]+( [a-z]+=[0-9]+)*$"
    return trimmed.range(of: pattern, options: .regularExpression) != nil ? trimmed : ""
  }

  /// callResult in EngineHost.kt.
  func call(op: String, input: String) -> [String: Any] {
    guard DigitvaIcd11Module.isOpName(op) else { return ["ok": false, "error": "bad_op", "status": 0, "nativeMs": 0.0] }
    guard initResult?["ok"] as? Bool == true else {
      return ["ok": false, "error": "not_initialized", "status": 503, "nativeMs": 0.0]
    }
    let start = DispatchTime.now()
    let (text, status) = Self.nativeCall(op: op, input: input)
    let nativeMs = Self.millis(since: start)
    guard let text, (200...299).contains(status) else {
      // The body of a failed call may echo the input or a stack trace: drop it.
      return ["ok": false, "error": "engine_status", "status": status, "nativeMs": nativeMs]
    }
    return ["ok": true, "status": status, "text": text, "nativeMs": nativeMs]
  }

  /// True when the engine initialised. Its error text is freed unread.
  private static func nativeInit(bundle: String, data: String) -> Bool {
    #if DIGITVA_ICD11_LINKED
    let error = bundle.withCString { b in data.withCString { d in digitva_icd11_init(b, d) } }
    if let error {
      digitva_icd11_free(error)
      return false
    }
    return true
    #else
    return false
    #endif
  }

  private static func nativeCall(op: String, input: String) -> (String?, Int) {
    #if DIGITVA_ICD11_LINKED
    var status: Int32 = 0
    let out = op.withCString { o in input.withCString { j in digitva_icd11_call(o, j, &status) } }
    guard let out else { return (nil, Int(status)) }
    defer { digitva_icd11_free(out) }
    return (String(cString: out), Int(status))
    #else
    return (nil, 0)
    #endif
  }
}
