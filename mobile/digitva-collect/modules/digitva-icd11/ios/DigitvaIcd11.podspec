# Local Expo module (modules/digitva-icd11), Collect Plus only: the offline WHO ICD-11 / DORIS engine in the app process.
#
# Staged by scripts/stage-engine.js stageIcd11Ios (plugins/with-ios-collect-plus.js runs it before pod install):
#   DigitvaIcd11Engine.xcframework  the NativeAOT engine (engine-src/build-ios.sh): a dynamic framework per slice,
#                                   embedded in the app by CocoaPods' framework embedding phase
#   Icd11Data/                      WHO data and who-files.json, shipped as the resource bundle DigitvaIcd11Data.bundle
# Only when both are present is DIGITVA_ICD11_LINKED set, so DigitvaIcd11Module.swift imports and calls the engine.
# Without them the module compiles and reports the engine unavailable.
here = __dir__
engine_present = File.directory?(File.join(here, 'DigitvaIcd11Engine.xcframework')) &&
                 File.file?(File.join(here, 'Icd11Data', 'who-files.json'))

Pod::Spec.new do |s|
  s.name           = 'DigitvaIcd11'
  s.version        = '1.0.0'
  s.summary        = 'Offline WHO ICD-11 engine for DigitVA Collect Plus'
  s.description    = 'Runs the NativeAOT ICD-API / DORIS engine (engine-src) on a dedicated worker thread.'
  s.author         = 'DigitVA'
  s.license        = { type: 'Proprietary', text: 'Part of DigitVA Collect. WHO ICD-11 data is CC BY-ND 3.0 IGO.' }
  s.homepage       = 'https://github.com/drguptavivek/DigitVA'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
  xcconfig = { 'DEFINES_MODULE' => 'YES' }
  if engine_present
    s.vendored_frameworks = 'DigitvaIcd11Engine.xcframework'
    # The folder itself (not a glob) keeps bundle/ and data/ as subfolders inside the resource bundle.
    s.resource_bundles = { 'DigitvaIcd11Data' => ['Icd11Data'] }
    xcconfig['SWIFT_ACTIVE_COMPILATION_CONDITIONS'] = '$(inherited) DIGITVA_ICD11_LINKED'
    Pod::UI.message('DigitvaIcd11: engine and WHO data vendored')
  else
    Pod::UI.message('DigitvaIcd11: no engine staged; the module reports the engine unavailable')
  end
  s.pod_target_xcconfig = xcconfig
end
