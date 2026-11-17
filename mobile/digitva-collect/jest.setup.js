// jest-expo's native JS logger probes an unavailable TurboModule in Node after
// tests complete. Keep the test runtime on Expo's web path for that probe;
// React Native Platform.OS remains controlled by each test's module mocks.
process.env.EXPO_OS = "web";

const originalWarn = console.warn.bind(console);
console.warn = (...args) => {
  if (String(args[0]).includes("An error occurred while requiring the 'ExpoModulesCoreJSLogger' module")) return;
  originalWarn(...args);
};

// expo-network has no native module under Node; the default is a connected phone. Tests override per case.
jest.mock("expo-network", () => ({
  getNetworkStateAsync: jest.fn(async () => ({ isConnected: true, isInternetReachable: true })),
  addNetworkStateListener: jest.fn(() => ({ remove: jest.fn() })),
}));

// expo-symbols' web view puts its `fallback` element in the rendered props, which `toJSON()` cannot serialise.
// A plain host view keeps the symbol names (`name`) and colour for assertions (src/Icon.tsx).
jest.mock("expo-symbols", () => {
  const React = require("react");
  const { View } = require("react-native");
  return {
    SymbolView: ({ name, tintColor, size, accessible, accessibilityLabel, importantForAccessibility }) =>
      React.createElement(View, { testID: "symbol", name, tintColor, style: { width: size, height: size }, accessible, accessibilityLabel, importantForAccessibility }),
  };
});

// Reanimated's native runtime is unavailable under Node, and its own mock needs it too. This stub keeps shared values
// across renders (collected in `__sharedValues`, in creation order) and evaluates animated styles on each render.
jest.mock("react-native-reanimated", () => {
  const React = require("react");
  const { View } = require("react-native");
  const sharedValues = [];
  return {
    __esModule: true,
    __sharedValues: sharedValues,
    default: { View, createAnimatedComponent: (component) => component },
    useSharedValue: (initial) => {
      const ref = React.useRef(null);
      if (!ref.current) { ref.current = { value: initial }; sharedValues.push(ref.current); }
      return ref.current;
    },
    useEvent: () => () => undefined,
    useAnimatedStyle: (fn) => fn(),
    withTiming: (value) => value,
  };
});
