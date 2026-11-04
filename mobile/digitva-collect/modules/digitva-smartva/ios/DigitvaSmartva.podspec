# Local Expo module (modules/digitva-smartva), Collect Plus only: the SmartVA engine in the app process on iOS.
#
# SmartvaRust.xcframework (a static framework per slice, built by scripts/build-smartva-ios.sh and copied here by
# scripts/stage-engine.js stageSmartvaIos) is vendored only when it is present. Then, and only then, the Swift
# compilation condition DIGITVA_SMARTVA_LINKED is set, so DigitvaSmartvaModule.swift imports the library and
# isAvailable() answers true. A build without the staged xcframework still compiles, with isAvailable() false.
xcframework_present = File.directory?(File.join(__dir__, 'SmartvaRust.xcframework'))

Pod::Spec.new do |s|
  s.name           = 'DigitvaSmartva'
  s.version        = '1.0.0'
  s.summary        = 'Offline SmartVA scoring for DigitVA Collect Plus'
  s.description    = 'Runs the SmartVA Rust engine (vendor/smartva-analyze) on a dedicated worker thread.'
  s.author         = 'DigitVA'
  s.license        = { type: 'Proprietary', text: 'Part of DigitVA Collect.' }
  s.homepage       = 'https://github.com/drguptavivek/DigitVA'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
  xcconfig = { 'DEFINES_MODULE' => 'YES' }
  if xcframework_present
    s.vendored_frameworks = 'SmartvaRust.xcframework'
    # chrono's time-zone lookup (iana-time-zone) calls CoreFoundation.
    s.frameworks = 'CoreFoundation'
    xcconfig['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] = '$(inherited) DIGITVA_SMARTVA_LINKED'
    Pod::UI.message('DigitvaSmartva: SmartvaRust.xcframework vendored')
  else
    Pod::UI.message('DigitvaSmartva: no SmartvaRust.xcframework staged; the module reports the engine unavailable')
  end
  s.pod_target_xcconfig = xcconfig
end
