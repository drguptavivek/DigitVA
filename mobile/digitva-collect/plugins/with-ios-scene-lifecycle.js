const { withAppDelegate, withInfoPlist } = require("@expo/config-plugins");

/**
 * iOS 27 stops at launch (EXC_BREAKPOINT in _UIApplicationEvaluateRuntimeIssueForNoSceneLifecycleAdoption) any app
 * built with the iOS 27 SDK that has not adopted the scene life cycle; iOS 26 only warns. Expo 57 ships the scene
 * delegate (ExpoAppSceneDelegate, Objective-C name EXExpoAppSceneDelegate), but its SDK 57 template still starts
 * React Native from the app delegate. This plugin registers the scene delegate in Info.plist and lets it start React
 * Native: the app delegate keeps creating the factory, conforms to ExpoReactNativeFactoryProvider, and no longer
 * makes its own window. Remove it once the Expo template does the same.
 */
const SCENE_DELEGATE = "EXExpoAppSceneDelegate";
const CLASS_LINE = /class AppDelegate: ExpoAppDelegate(, ExpoReactNativeFactoryProvider)? \{/;
const WINDOW_START =
  /\n#if os\(iOS\) \|\| os\(tvOS\)\n\s*window = UIWindow\(frame: UIScreen\.main\.bounds\)\n\s*factory\.startReactNative\([^)]*\)\n#endif\n/;

function patchAppDelegate(contents) {
  if (typeof contents !== "string") throw new Error("iOS AppDelegate contents must be a string");
  if (!CLASS_LINE.test(contents)) throw new Error("Unsupported iOS AppDelegate: no ExpoAppDelegate subclass");
  let out = contents.replace(CLASS_LINE, "class AppDelegate: ExpoAppDelegate, ExpoReactNativeFactoryProvider {");
  if (WINDOW_START.test(out)) {
    out = out.replace(WINDOW_START, "\n    // The scene delegate (EXExpoAppSceneDelegate) makes the window and starts React Native.\n");
  } else if (out.includes("UIWindow(frame: UIScreen.main.bounds)")) {
    throw new Error("Unsupported iOS AppDelegate: cannot move the window start to the scene delegate");
  }
  return out;
}

function sceneManifest() {
  return {
    UIApplicationSupportsMultipleScenes: false,
    UISceneConfigurations: {
      UIWindowSceneSessionRoleApplication: [
        { UISceneConfigurationName: "Default Configuration", UISceneDelegateClassName: SCENE_DELEGATE },
      ],
    },
  };
}

function withIosSceneLifecycle(config) {
  config = withInfoPlist(config, (mod) => {
    mod.modResults.UIApplicationSceneManifest = sceneManifest();
    return mod;
  });
  return withAppDelegate(config, (mod) => {
    if (mod.modResults.language !== "swift") throw new Error("iOS AppDelegate must be Swift");
    mod.modResults.contents = patchAppDelegate(mod.modResults.contents);
    return mod;
  });
}

module.exports = withIosSceneLifecycle;
module.exports.patchAppDelegate = patchAppDelegate;
module.exports.sceneManifest = sceneManifest;
