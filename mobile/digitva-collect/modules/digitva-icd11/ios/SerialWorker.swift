import Foundation

/**
 * One long-lived thread that runs submitted blocks in order: the iOS stand-in for the single-thread executor that owns
 * the engine on Android. A dedicated Thread rather than a serial DispatchQueue, because a GCD worker thread has a fixed
 * 512 KiB stack and the native engines need more (stackSize below); the thread is started on the first submit, so a
 * build or a session that never scores never creates it.
 */
// Its state is guarded by `condition`, so it may be shared across threads.
final class SerialWorker: @unchecked Sendable {
  private let condition = NSCondition()
  private var blocks: [() -> Void] = []
  private var thread: Thread?
  private let name: String
  private let stackSize: Int

  init(name: String, stackSize: Int) {
    self.name = name
    self.stackSize = stackSize
  }

  func submit(_ block: @escaping () -> Void) {
    condition.lock()
    blocks.append(block)
    if thread == nil {
      let worker = Thread { [weak self] in self?.loop() }
      worker.name = name
      worker.stackSize = stackSize
      worker.qualityOfService = .userInitiated
      thread = worker
      worker.start()
    }
    condition.signal()
    condition.unlock()
  }

  private func loop() {
    while true {
      condition.lock()
      while blocks.isEmpty { condition.wait() }
      let block = blocks.removeFirst()
      condition.unlock()
      autoreleasepool { block() }
    }
  }
}
