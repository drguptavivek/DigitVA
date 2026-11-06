# Collect Plus only (APP_VARIANT=plus): plugins/with-ios-collect-plus.js keeps this module out of the plain build and
# stages SmartvaRust.xcframework (scripts/build-smartva-ios.sh) into Engine/ (git-ignored) before pod install.
unless File.exist?(File.join(__dir__, 'Engine', 'SmartvaRust.xcframework', 'Info.plist'))
  raise 'Collect Plus: SmartVA is not staged for iOS. Run "node modules/digitva-smartva/scripts/stage-engine.js --ios" from ' \
        'mobile/digitva-collect (it needs private/generated/smartva-ios/SmartvaRust.xcframework from scripts/build-smartva-ios.sh).'
end

Pod::Spec.new do |s|
  s.name           = 'DigitvaSmartva'
  s.version        = '0.1.0'
  s.summary        = 'Offline SmartVA scoring for DigitVA Collect Plus'
  s.license        = { :type => 'Proprietary' }
  s.author         = 'DigitVA'
  s.homepage       = 'https://digitvav3.causeofdeathindia.com'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
  # The MIT smartva-rust crate (vendor/smartva-analyze/rust, feature mobile-core) as a static library with its C header.
  s.vendored_frameworks = 'Engine/SmartvaRust.xcframework'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
