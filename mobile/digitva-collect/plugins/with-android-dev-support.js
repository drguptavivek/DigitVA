const { withMainApplication } = require('@expo/config-plugins');

/**
 * Set React Native developer support from this app's Android build type.
 * The Expo factory's library default can be false in debug APKs.
 */
function enableAndroidDevSupport(contents) {
  const callStart = contents.indexOf('ExpoReactHostFactory.getDefaultReactHost(');
  if (callStart === -1 || contents.indexOf('ExpoReactHostFactory.getDefaultReactHost(', callStart + 1) !== -1) {
    throw new Error('Expected exactly one ExpoReactHostFactory.getDefaultReactHost call in MainApplication.kt');
  }

  const callEnd = contents.indexOf('\n    )\n  }', callStart);
  if (callEnd === -1) {
    throw new Error('Unsupported MainApplication.kt getDefaultReactHost template');
  }

  const call = contents.slice(callStart, callEnd);
  if (!call.includes('packageList =') || !call.includes('PackageList(this).packages.apply {')) {
    throw new Error('Unsupported MainApplication.kt getDefaultReactHost arguments');
  }

  if (/\buseDevSupport\s*=\s*BuildConfig\.DEBUG\b/.test(call)) {
    return contents;
  }
  if (/\buseDevSupport\s*=/.test(call)) {
    throw new Error('Unexpected useDevSupport value in MainApplication.kt');
  }

  return `${contents.slice(0, callEnd)},\n      useDevSupport = BuildConfig.DEBUG${contents.slice(callEnd)}`;
}

module.exports = function withAndroidDevSupport(config) {
  return withMainApplication(config, (config) => {
    if (config.modResults.language !== 'kt') {
      throw new Error('withAndroidDevSupport requires a Kotlin MainApplication.kt');
    }

    config.modResults.contents = enableAndroidDevSupport(config.modResults.contents);
    return config;
  });
};

module.exports.enableAndroidDevSupport = enableAndroidDevSupport;
