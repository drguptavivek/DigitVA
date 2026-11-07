/**
 * A stored photo full screen (the form engine's `ImageViewer` slot on the phone): pinch to zoom 1x-5x, pan while
 * zoomed, double-tap to zoom in or back to fit, a rotate button and Close. Rotation and zoom are view-only; the
 * stored image never changes. The uri is the control's short-lived plain preview copy (src/mediaFiles.ts).
 */
import { useState } from "react";
import { Image, Modal, Pressable, StyleSheet, View } from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import type { WhoVaImageViewerProps } from "@drguptavivek/who-2022-va";

import { Icon, icons } from "./Icon";

const MIN_SCALE = 1;
const MAX_SCALE = 5;
const DOUBLE_TAP_SCALE = 2.5;
// Always dark, like the camera and the QR scanner (design sheet 06).
const BACKDROP = "#000000";
const ON_BACKDROP = "#ffffff";

export function AttachmentImageViewer({ uri, accessibilityLabel, rotateLabel, closeLabel, onClose }: WhoVaImageViewerProps) {
  const insets = useSafeAreaInsets();
  const [rotation, setRotation] = useState(0);
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const savedX = useSharedValue(0);
  const savedY = useSharedValue(0);

  // ponytail: pan is not bounded to the image's edges; add bounds if interviewers lose the page off screen.
  const pinch = Gesture.Pinch()
    .onUpdate((event) => {
      scale.value = Math.min(MAX_SCALE, Math.max(MIN_SCALE, savedScale.value * event.scale));
    })
    .onEnd(() => {
      savedScale.value = scale.value;
      if (scale.value <= MIN_SCALE) {
        x.value = withTiming(0);
        y.value = withTiming(0);
        savedX.value = 0;
        savedY.value = 0;
      }
    });
  const pan = Gesture.Pan()
    .averageTouches(true)
    .onUpdate((event) => {
      if (scale.value <= MIN_SCALE) return;
      x.value = savedX.value + event.translationX;
      y.value = savedY.value + event.translationY;
    })
    .onEnd(() => {
      savedX.value = x.value;
      savedY.value = y.value;
    });
  const doubleTap = Gesture.Tap()
    .numberOfTaps(2)
    .onEnd(() => {
      const next = scale.value > MIN_SCALE ? MIN_SCALE : DOUBLE_TAP_SCALE;
      scale.value = withTiming(next);
      savedScale.value = next;
      x.value = withTiming(0);
      y.value = withTiming(0);
      savedX.value = 0;
      savedY.value = 0;
    });
  const gestures = Gesture.Simultaneous(pinch, pan, doubleTap);
  const zoomed = useAnimatedStyle(() => ({
    transform: [{ translateX: x.value }, { translateY: y.value }, { scale: scale.value }],
  }));

  return (
    <Modal visible animationType="fade" statusBarTranslucent onRequestClose={onClose} supportedOrientations={["portrait", "landscape"]}>
      {/* A Modal is a separate native root on Android: gestures inside it need their own handler root. */}
      <GestureHandlerRootView style={styles.root}>
        <View accessibilityViewIsModal style={styles.root}>
          <GestureDetector gesture={gestures}>
            <Animated.View style={[styles.stage, zoomed]}>
              <Image
                accessibilityLabel={accessibilityLabel}
                testID="photo-viewer-image"
                source={{ uri }}
                resizeMode="contain"
                style={[styles.image, { transform: [{ rotate: `${rotation}deg` }] }]}
              />
            </Animated.View>
          </GestureDetector>
          <View style={[styles.bar, { paddingTop: insets.top + 8, paddingRight: insets.right + 12 }]}>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={rotateLabel}
              testID="photo-viewer-rotate"
              hitSlop={8}
              style={styles.button}
              onPress={() => setRotation((current) => (current + 90) % 360)}
            >
              <Icon name={icons.rotate} color={ON_BACKDROP} size={26} />
            </Pressable>
            <Pressable
              accessibilityRole="button"
              accessibilityLabel={closeLabel}
              testID="photo-viewer-close"
              hitSlop={8}
              style={styles.button}
              onPress={onClose}
            >
              <Icon name={icons.close} color={ON_BACKDROP} size={26} />
            </Pressable>
          </View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: BACKDROP },
  stage: { flex: 1, alignItems: "center", justifyContent: "center" },
  image: { width: "100%", height: "100%" },
  bar: { position: "absolute", top: 0, left: 0, right: 0, flexDirection: "row", justifyContent: "flex-end", gap: 12 },
  button: { minWidth: 48, minHeight: 48, alignItems: "center", justifyContent: "center" },
});
