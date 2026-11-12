import ExpoModulesCore

/**
 * JS face of the offline WHO ICD-11 / DORIS engine on iOS: the same functions, event and result maps as
 * DigitvaIcd11Module.kt, so src/offlineEngine.ts has no platform branch. Requests run in order on one engine thread
 * (EngineWorker); init happens once per app process and a failed init is sticky until the app restarts. Engine error
 * payloads never reach here: JS gets a status number or a short error code. Progress of an init is the
 * "icd11Progress" event ({ phase, percent }, percent -1 when unknown).
 *
 * There is no engine process to lose, so ERR_ICD11_PROCESS fires only for a request whose module went away (a JS
 * reload) before the engine thread reached it. The engine shares the app's
 * memory (Android measured 0.5 to 1.1 GB resident), so iOS may end the whole app under memory pressure.
 */
public class DigitvaIcd11Module: Module {
  // One engine thread per app process: a reloaded JS runtime gets a new module, never a second thread. Its host then
  // re-runs init, which the bridge answers at once (already up).
  private static let worker = EngineWorker()
  // Created and used on the worker thread only.
  private var host: EngineHost?

  private func onWorker(_ promise: Promise, _ work: @escaping (EngineHost) -> [String: Any]) {
    Self.worker.submit { [weak self] in
      guard let self else { return promise.reject("ERR_ICD11_PROCESS", "engine process stopped") }
      let host = self.host ?? EngineHost { [weak self] phase, percent in
        self?.sendEvent("icd11Progress", ["phase": phase, "percent": percent])
      }
      self.host = host
      promise.resolve(boundReply(work(host)))
    }
  }

  public func definition() -> ModuleDefinition {
    Name("DigitvaIcd11")

    Events("icd11Progress")

    // Whether this build carries the engine and its data; does not start it.
    AsyncFunction("isAvailable") { () -> Bool in
      EngineData.packaged() != nil
    }

    // The engine runs in-process and cannot unload: nothing to stop (Android ends its process, digitva-xhz7).
    AsyncFunction("release") { () -> Bool in true }

    AsyncFunction("init") { (promise: Promise) in
      self.onWorker(promise) { $0.initEngine() }
    }

    // WHO files ship with app updates only; the same answer Icd11Service gives.
    AsyncFunction("updateWhoFiles") { () -> [String: Any] in
      ["ok": false, "error": "bundled_only"]
    }

    // `op` is the bridge's op name and `input` the JSON object of its arguments. Only the name's shape is checked here: the bridge
    // owns the list of ops and answers an unknown one with status 400.
    AsyncFunction("call") { (op: String, input: String, promise: Promise) in
      guard isOpName(op) else { return promise.reject("ERR_ICD11_OP", "bad engine op") }
      self.onWorker(promise) { $0.call(op, input) }
    }
  }
}
