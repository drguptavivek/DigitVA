Pod::Spec.new do |s|
  s.name           = 'DigitvaDeviceInfo'
  s.version        = '0.1.0'
  s.summary        = 'Coarse device characteristics for the DigitVA app-performance aggregate'
  s.license        = { :type => 'Proprietary' }
  s.author         = 'DigitVA'
  s.homepage       = 'https://digitvav3.causeofdeathindia.com'
  s.platforms      = { :ios => '16.4' }
  s.swift_version  = '5.9'
  s.source         = { git: '' }
  s.static_framework = true

  s.dependency 'ExpoModulesCore'

  s.source_files = '*.swift'
  s.pod_target_xcconfig = {
    'DEFINES_MODULE' => 'YES',
    'SWIFT_COMPILATION_MODE' => 'wholemodule'
  }
end
