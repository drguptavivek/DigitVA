# Collect Plus only (APP_VARIANT=plus): plugins/with-ios-collect-plus.js keeps this module out of the plain build and
# stages the engine from private/ into Engine/ (git-ignored) before pod install. Fail here, with a plain message,
# rather than build a Plus app without it.
engine = File.join(__dir__, 'Engine')
unless File.exist?(File.join(engine, 'DigitvaIcd11Engine.xcframework', 'Info.plist')) && File.directory?(File.join(engine, 'digitva-icd11', 'data'))
  raise 'Collect Plus: the offline ICD-11 engine is not staged for iOS. Run "node modules/digitva-icd11/scripts/stage-engine.js --ios" ' \
        'from mobile/digitva-collect (it needs engine-src/build-ios.sh output in private/icd11-offline-spike/bridge-aot/pub-ios/), ' \
        'or re-run "APP_VARIANT=plus npx expo prebuild --platform ios".'
end

Pod::Spec.new do |s|
  s.name           = 'DigitvaIcd11'
  s.version        = '0.1.0'
  s.summary        = 'Offline WHO ICD-11 / DORIS engine for DigitVA Collect Plus'
  s.license        = { :type => 'Proprietary' }
  s.author         = 'DigitVA'
  s.homepage       = 'https://digitvav3.causeofdeathindia.com'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
  # Bridge.cs + WHO ICD-API 2.6.0, NativeAOT (engine-src/build-ios.sh): a dynamic framework, embedded and signed with the app.
  s.vendored_frameworks = 'Engine/DigitvaIcd11Engine.xcframework'
  # A folder, not a glob, so the tree (bundle/, data/, who-files.json) keeps its layout in the app bundle.
  s.resources = ['Engine/digitva-icd11']
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
