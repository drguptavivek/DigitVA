/**
 * Web: no gesture root. The browser has no gesture screens, and importing react-native-gesture-handler
 * here would put it, Reanimated and Hammer.js in the start-up bundle (scripts/profile-expo-web.mjs gate).
 */
export { View as GestureRoot } from "react-native";
