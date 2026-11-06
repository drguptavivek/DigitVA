import ExpoModulesCore
import Foundation

/**
 * iOS twin of DigitvaDeviceInfoModule.kt: the same coarse buckets and keys. Every field has an iOS source:
 * device_type from the hardware model ("iPad…" tablet, "iPhone…"/"iPod…" phone, a simulator "emulator", an iOS app
 * running on a Mac "other"), ram_bucket from the physical memory, core_bucket from the active processor count, and
 * manufacturer is always "apple". No model, identifier or permission is exposed to JavaScript, and UIKit is not
 * touched, so this is safe off the main thread.
 */
public class DigitvaDeviceInfoModule: Module {
  private static func hardwareModel() -> String {
    var size = 0
    guard sysctlbyname("hw.machine", nil, &size, nil, 0) == 0, size > 0 else { return "" }
    var model = [CChar](repeating: 0, count: size)
    guard sysctlbyname("hw.machine", &model, &size, nil, 0) == 0 else { return "" }
    return String(cString: model)
  }

  private static func deviceType() -> String {
    #if targetEnvironment(simulator)
    return "emulator"
    #else
    if ProcessInfo.processInfo.isiOSAppOnMac { return "other" }
    let model = hardwareModel()
    if model.hasPrefix("iPad") { return "tablet" }
    if model.hasPrefix("iPhone") || model.hasPrefix("iPod") { return "phone" }
    return "other"
    #endif
  }

  private static func ramBucket() -> String {
    let gib = Double(ProcessInfo.processInfo.physicalMemory) / (1024.0 * 1024.0 * 1024.0)
    switch gib {
    case ...0: return "unknown"
    case ..<2: return "lt2"
    case ..<4: return "2_3"
    case ..<6: return "4_5"
    case ..<8: return "6_7"
    case ..<12: return "8_11"
    default: return "12plus"
    }
  }

  private static func coreBucket() -> String {
    switch ProcessInfo.processInfo.activeProcessorCount {
    case 1...2: return "1_2"
    case 3...4: return "3_4"
    case 5...8: return "5_8"
    case let cores where cores > 8: return "9plus"
    default: return "unknown"
    }
  }

  public func definition() -> ModuleDefinition {
    Name("DigitvaDeviceInfo")

    Function("getHardwareProfile") { () -> [String: String] in
      [
        "device_type": Self.deviceType(),
        "ram_bucket": Self.ramBucket(),
        "core_bucket": Self.coreBucket(),
        "manufacturer": "apple",
      ]
    }
  }
}
