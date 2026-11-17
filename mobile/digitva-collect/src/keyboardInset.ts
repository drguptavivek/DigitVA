/**
 * Bottom space for the on-screen keyboard where Android does not make room for it itself.
 * Edge-to-edge apps on older Android (seen on Android 9) keep the full window height when the keyboard opens,
 * so a field low on the screen sits under the keyboard. Where the window does shrink (newer Android), the inset
 * stays 0 so the space is never added twice.
 */
import { useEffect, useState } from "react";
import { Dimensions, Keyboard, Platform } from "react-native";

/** The keyboard height the window did not already give up; 0 when the system resized the window. */
export function missingKeyboardSpace(windowHeight: number, screenHeight: number, keyboardTop: number): number {
  const covered = windowHeight - keyboardTop;
  // The window ends at or above the keyboard's top: the system already made room.
  if (covered <= 0 || keyboardTop >= screenHeight) return 0;
  return Math.round(covered);
}

export function useKeyboardInset(): number {
  const [inset, setInset] = useState(0);
  useEffect(() => {
    if (Platform.OS !== "android") return;
    const show = Keyboard.addListener("keyboardDidShow", (event) => {
      const { height: windowHeight } = Dimensions.get("window");
      const { height: screenHeight } = Dimensions.get("screen");
      setInset(missingKeyboardSpace(windowHeight, screenHeight, event.endCoordinates.screenY));
    });
    const hide = Keyboard.addListener("keyboardDidHide", () => setInset(0));
    return () => {
      show.remove();
      hide.remove();
    };
  }, []);
  return inset;
}
