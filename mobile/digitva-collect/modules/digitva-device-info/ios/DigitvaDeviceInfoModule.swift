import ExpoModulesCore
import Foundation

/**
 * Coarse device characteristics for the optional app-performance aggregate: the iOS twin of
 * android/.../DigitvaDeviceInfoModule.kt, with the same keys, values and bucket boundaries
 * (src/performanceTelemetry.ts validates them). No model, location, identifier or permission is exposed to JavaScript.
 *
 * Everything here is read without UIKit: `getHardwareProfile` is a synchronous function that runs on the JavaScript
 * thread, and UIDevice is main-actor isolated. The device family comes from the `hw.machine` sysctl instead
 * ("iPhone…", "iPad…"), which also describes the hardware when an iPhone-only app runs on an iPad.
 */
public final class DigitvaDeviceInfoModule: Module {
  public func definition() -> ModuleDefinition {
    Name("DigitvaDeviceInfo")

    Function("getHardwareProfile") { () -> [String: String] in
      return [
        "device_type": Self.deviceType(),
        "ram_bucket": Self.ramBucket(),
        "core_bucket": Self.coreBucket(),
        "manufacturer": "apple",
      ]
    }
  }

  /// "iPhone15,2", "iPad13,4", ... on hardware; nil when the sysctl fails.
  private static func machine() -> String? {
    var size = 0
    guard sysctlbyname("hw.machine", nil, &size, nil, 0) == 0, size > 0 else { return nil }
    var bytes = [CChar](repeating: 0, count: size)
    guard sysctlbyname("hw.machine", &bytes, &size, nil, 0) == 0 else { return nil }
    return String(cString: bytes)
  }

  static func deviceType() -> String {
    #if targetEnvironment(simulator)
    return "emulator"
    #else
    // An iPhone/iPad app running on an Apple-silicon Mac is neither a phone nor a tablet.
    if ProcessInfo.processInfo.isiOSAppOnMac || ProcessInfo.processInfo.isMacCatalystApp { return "other" }
    guard let machine = machine() else { return "other" }
    if machine.hasPrefix("iPad") { return "tablet" }
    if machine.hasPrefix("iPhone") { return "phone" }
    return "other"
    #endif
  }

  /// Same boundaries as the Kotlin module (GiB of total memory). Like Android's totalMem, physicalMemory reads a little
  /// under the marketed size, so a "4 GB" phone lands in 2_3 on both platforms.
  static func ramBucket() -> String {
    let gib = Double(ProcessInfo.processInfo.physicalMemory) / (1024.0 * 1024.0 * 1024.0)
    switch gib {
    case ..<0.000_001: return "unknown"
    case ..<2: return "lt2"
    case ..<4: return "2_3"
    case ..<6: return "4_5"
    case ..<8: return "6_7"
    case ..<12: return "8_11"
    default: return "12plus"
    }
  }

  static func coreBucket() -> String {
    let cores = ProcessInfo.processInfo.activeProcessorCount
    switch cores {
    case 1...2: return "1_2"
    case 3...4: return "3_4"
    case 5...8: return "5_8"
    default: return cores > 8 ? "9plus" : "unknown"
    }
  }
}
