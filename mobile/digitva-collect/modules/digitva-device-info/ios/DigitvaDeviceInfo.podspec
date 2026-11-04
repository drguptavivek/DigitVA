# Local Expo module (modules/digitva-device-info): coarse hardware buckets for the optional performance aggregate.
Pod::Spec.new do |s|
  s.name           = 'DigitvaDeviceInfo'
  s.version        = '1.0.0'
  s.summary        = 'Coarse device characteristics for DigitVA Collect'
  s.description    = 'Device type, RAM and core buckets and the manufacturer bucket; no model, identifier or permission.'
  s.author         = 'DigitVA'
  s.license        = { type: 'Proprietary', text: 'Part of DigitVA Collect.' }
  s.homepage       = 'https://github.com/drguptavivek/DigitVA'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES'
  }
  s.source_files = '**/*.swift'
end
