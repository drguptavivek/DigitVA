import DigitvaIcd11Engine
import Foundation
import os

/**
 * iOS twin of EngineHost.kt: the engine's lifecycle and calls, with the same result maps and error codes. iOS has no
 * second process, so the engine runs inside the app on EngineWorker's one thread (DigitvaIcd11Module never calls this
 * from anywhere else): init once per app process, failure sticky until the app restarts. The engine cannot be unloaded
 * (Bridge.cs has no shutdown), so its memory stays until the app ends. Engine error text can hold stack traces and
 * certificate content: it is freed unread, never logged or returned.
 *
 * Android's "unavailable" (no shim) and "load_failed" (dlopen or a missing export) cannot happen: the framework is
 * linked, so an engine without digitva_icd11_call fails the app's link, not a phone.
 */
final class EngineHost {
  private let progress: (_ phase: String, _ percent: Int) -> Void
  // Touched only on the worker thread.
  private var initResult: [String: Any]?

  init(progress: @escaping (_ phase: String, _ percent: Int) -> Void) {
    self.progress = progress
  }

  private static func millis(since start: DispatchTime) -> Double {
    Double(DispatchTime.now().uptimeNanoseconds - start.uptimeNanoseconds) / 1_000_000
  }

  private static func fail(_ code: String, copyMs: Double = 0, initMs: Double = 0, totalMs: Double = 0) -> [String: Any] {
    ["ok": false, "error": code, "copyMs": copyMs, "initMs": initMs, "ms": totalMs, "cached": false]
  }

  func initEngine() -> [String: Any] {
    if var cached = initResult {
      cached["cached"] = true
      cached["ms"] = 0.0
      return cached
    }
    let start = DispatchTime.now()
    let result: [String: Any]
    do {
      let record = EngineData.setupRecord()
      // A setup that started and never finished: start from the packaged copies.
      let interrupted = record?["state"] as? String == "attempt"
      if interrupted { EngineData.discard() }
      let copyStart = DispatchTime.now()
      let root = try EngineData.ensureCopied { self.progress("copy", $0) }
      let copyMs = Self.millis(since: copyStart)
      let data = root.appendingPathComponent("data")
      // The engine's .NET runtime reads TMPDIR from the C environment.
      setenv("TMPDIR", data.path + "/", 1)
      let repaired = try EngineData.repair(root, EngineData.shippedWho())
      Self.guardNetwork()
      let recordSetup = record == nil || interrupted
      if recordSetup { try EngineData.markAttempt() }
      progress("engine", -1)
      let initStart = DispatchTime.now()
      let error = digitva_icd11_init(root.appendingPathComponent("bundle").path, data.path)
      let initMs = Self.millis(since: initStart)
      if let error {
        digitva_icd11_free(error)
        // Derived files may be half written; start from clean data after a restart.
        EngineData.discard()
        result = Self.fail("init_failed", copyMs: copyMs, initMs: initMs, totalMs: Self.millis(since: start))
      } else {
        if recordSetup || !repaired.isEmpty { try EngineData.writeShipped() }
        progress("ready", 100)
        result = ["ok": true, "copyMs": copyMs, "initMs": initMs, "ms": Self.millis(since: start), "cached": false,
                  "phases": Self.phases(root), "setup": EngineData.shippedSummary]
      }
    } catch {
      // Type name only: messages can carry paths or data.
      Logger(subsystem: "DigitvaIcd11", category: "engine").warning("init failed: \(String(describing: type(of: error)), privacy: .public)")
      result = Self.fail("data_copy_failed", totalMs: Self.millis(since: start))
    }
    initResult = result
    return result
  }

  /**
   * As on Android (EngineHost.guardNetwork): WHO's loaders try to download files that are already shipped, and a dead
   * proxy makes each attempt fail at once so the engine falls back to the local files. On iOS .NET uses Apple's TLS,
   * so without this an online device would really fetch from WHO at init. These variables are process-wide here; the
   * app's own networking (NSURLSession) does not read them.
   */
  private static func guardNetwork() {
    for name in ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"] { setenv(name, "http://127.0.0.1:9", 1) }
  }

  /** The bridge's phase end times ("config=… ready=…"); numbers and fixed labels only, else "". */
  private static func phases(_ root: URL) -> String {
    let text = ((try? String(contentsOf: root.appendingPathComponent("init-timings.txt"), encoding: .utf8)) ?? "")
      .trimmingCharacters(in: .whitespacesAndNewlines)
    return text.range(of: #"^[a-z]+=[0-9]+( [a-z]+=[0-9]+)*$"#, options: .regularExpression) != nil && !text.contains("\n") ? text : ""
  }

  /** One engine call: [op] the bridge's op name (Bridge.cs owns the list; only its shape is checked) and [input] its JSON arguments. */
  func call(_ op: String, _ input: String) -> [String: Any] {
    guard isOpName(op) else { return ["ok": false, "error": "bad_op", "status": 0, "nativeMs": 0.0] }
    guard initResult?["ok"] as? Bool == true else { return ["ok": false, "error": "not_initialized", "status": 503, "nativeMs": 0.0] }
    var status: Int32 = 0
    let start = DispatchTime.now()
    let out = digitva_icd11_call(op, input, &status)
    let nativeMs = Self.millis(since: start)
    guard let out else { return ["ok": false, "error": "engine_status", "status": Int(status), "nativeMs": nativeMs] }
    defer { digitva_icd11_free(out) }
    // The body of a failed call may echo the input or a stack trace: drop it.
    guard (200...299).contains(status) else { return ["ok": false, "error": "engine_status", "status": Int(status), "nativeMs": nativeMs] }
    return ["ok": true, "status": Int(status), "text": String(cString: out), "nativeMs": nativeMs]
  }
}

/** The shape of an op name, Icd11Service.OP_NAME on Android: 1 to 32 of a-z and "_". */
func isOpName(_ op: String) -> Bool {
  (1...32).contains(op.utf8.count) && op.utf8.allSatisfy { ($0 >= 0x61 && $0 <= 0x7a) || $0 == 0x5f }
}

/** Same cap as Icd11Service.MAX_TEXT_CHARS (a Binder limit there), kept so JS sees the same replies on both platforms. */
let maxTextChars = 250_000

/** [map] with a `text` over the cap replaced by `{ok:false, error:"too_large"}`, the other entries kept (Icd11Service.boundReply). */
func boundReply(_ map: [String: Any]) -> [String: Any] {
  guard let text = map["text"] as? String, text.utf16.count > maxTextChars else { return map }
  var bounded = map
  bounded["text"] = nil
  bounded["ok"] = false
  bounded["error"] = "too_large"
  return bounded
}

/**
 * One thread that owns the engine, jobs first come first served (Icd11Service's worker). A call queued after an init
 * runs after it, so no call reaches an engine that is not up yet. Its stack is 32 MB like Android's: NativeAOT
 * start-up is stack hungry, and a Dispatch queue thread has 512 KB.
 */
final class EngineWorker {
  private let condition = NSCondition()
  private var jobs: [() -> Void] = []
  private var thread: Thread?

  func submit(_ job: @escaping () -> Void) {
    condition.lock()
    jobs.append(job)
    if thread == nil {
      let worker = Thread { [unowned self] in self.run() }
      worker.name = "icd11-engine"
      worker.stackSize = 32 << 20
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
