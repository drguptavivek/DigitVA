// jest-expo's native JS logger probes an unavailable TurboModule in Node after
// tests complete. Keep the test runtime on Expo's web path for that probe;
// React Native Platform.OS remains controlled by each test's module mocks.
process.env.EXPO_OS = "web";

const originalWarn = console.warn.bind(console);
console.warn = (...args) => {
  if (String(args[0]).includes("An error occurred while requiring the 'ExpoModulesCoreJSLogger' module")) return;
  originalWarn(...args);
};
