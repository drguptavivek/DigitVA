/**
 * The phone coding workspace's full-screen image viewer. `ImageViewerProvider` wraps one category page: it knows that
 * page's image attachments in display order and renders the viewer when an inline image calls `useImageViewer()`.
 * The viewer shows one image at a time with pinch zoom (1x-5x), pan while zoomed (kept inside the image area),
 * double-tap zoom, rotate, previous/next (wrapping) and Close. Rotation and zoom are view-only and reset per image.
 *
 * Images load through the page's own `renderMedia` slot, handed a `renderImage` callback, so online media keeps the
 * bearer download to a private cache file (AttachmentMedia.native.tsx) and offline drafts keep the encrypted store
 * (LocalAttachmentMedia.native.tsx). Each image is keyed by path: its file is deleted when the next image replaces
 * it or the viewer closes. Native only: gesture-handler and reanimated must not reach the web bundle.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Image, Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { Gesture, GestureDetector, GestureHandlerRootView } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";
import { useSafeAreaInsets } from "react-native-safe-area-context";

export type ViewerImage = { path: string; label: string };
export type RenderMedia = (attachmentPath: string, renderImage?: (uri: string) => ReactNode) => ReactNode;

const MIN_SCALE = 1;
const MAX_SCALE = 5;
const DOUBLE_TAP_SCALE = 2.5;
const ZOOM_STEP = 1.5;
// Always dark, like the camera and the QR scanner.
const BACKDROP = "#000000";
const ON_BACKDROP = "#ffffff";
// Behind the title and controls, so they stay readable over a zoomed image.
const SCRIM = "rgba(0,0,0,0.6)";

function clamp(value: number, low: number, high: number) {
  "worklet";
  return Math.min(high, Math.max(low, value));
}

const OpenContext = createContext<((path: string) => void) | null>(null);

/** Opens the viewer at an image path; null outside a category page (the image is then not tappable). */
export const useImageViewer = () => useContext(OpenContext);

export function ImageViewerProvider({ images, renderMedia, children }: { images: ViewerImage[]; renderMedia?: RenderMedia; children: ReactNode }) {
  const [start, setStart] = useState<string | null>(null);
  const key = images.map((image) => image.path).join("|");
  // A different page's images are not this viewer's list.
  useEffect(() => setStart(null), [key]);
  const open = useCallback((path: string) => setStart(path), []);
  return (
    <OpenContext.Provider value={renderMedia ? open : null}>
      {children}
      {renderMedia && start ? <ImageViewer images={images} start={start} renderMedia={renderMedia} onClose={() => setStart(null)} /> : null}
    </OpenContext.Provider>
  );
}

function Control({ label, text, onPress }: { label: string; text: string; onPress: () => void }) {
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={label} hitSlop={4} style={styles.button} onPress={onPress}>
      <Text style={styles.glyph}>{text}</Text>
    </Pressable>
  );
}

function ImageViewer({ images, start, renderMedia, onClose }: { images: ViewerImage[]; start: string; renderMedia: RenderMedia; onClose: () => void }) {
  const insets = useSafeAreaInsets();
  const list = images.some((image) => image.path === start) ? images : [{ path: start, label: "" }];
  const [index, setIndex] = useState(Math.max(0, list.findIndex((image) => image.path === start)));
  const [rotation, setRotation] = useState(0);
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const x = useSharedValue(0);
  const y = useSharedValue(0);
  const savedX = useSharedValue(0);
  const savedY = useSharedValue(0);
  const stageW = useSharedValue(0);
  const stageH = useSharedValue(0);

  const current = list[index];

  // ponytail: zoom is about the stage centre, not the pinch point; add focal-point maths if reviewers miss it.
  const pinch = Gesture.Pinch()
    .onUpdate((event) => {
      scale.value = clamp(savedScale.value * event.scale, MIN_SCALE, MAX_SCALE);
      const mx = (stageW.value * (scale.value - 1)) / 2;
      const my = (stageH.value * (scale.value - 1)) / 2;
      x.value = clamp(x.value, -mx, mx);
      y.value = clamp(y.value, -my, my);
    })
    .onEnd(() => {
      savedScale.value = scale.value;
      savedX.value = x.value;
      savedY.value = y.value;
    });
  const pan = Gesture.Pan()
    .averageTouches(true)
    .onUpdate((event) => {
      if (scale.value <= MIN_SCALE) return;
      const mx = (stageW.value * (scale.value - 1)) / 2;
      const my = (stageH.value * (scale.value - 1)) / 2;
      x.value = clamp(savedX.value + event.translationX, -mx, mx);
      y.value = clamp(savedY.value + event.translationY, -my, my);
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

  const resetView = () => {
    scale.value = 1;
    savedScale.value = 1;
    x.value = 0;
    y.value = 0;
    savedX.value = 0;
    savedY.value = 0;
  };
  const zoomBy = (factor: number) => {
    const next = clamp(scale.value * factor, MIN_SCALE, MAX_SCALE);
    if (next <= MIN_SCALE) return resetView();
    scale.value = next;
    savedScale.value = next;
    x.value = savedX.value = clamp(x.value, -(stageW.value * (next - 1)) / 2, (stageW.value * (next - 1)) / 2);
    y.value = savedY.value = clamp(y.value, -(stageH.value * (next - 1)) / 2, (stageH.value * (next - 1)) / 2);
  };
  const move = (delta: number) => {
    setIndex((at) => (at + delta + list.length) % list.length);
    setRotation(0);
    resetView();
  };
  const rotate = (delta: number) => setRotation((degrees) => (degrees + delta + 360) % 360);

  const renderImage = (uri: string) => (
    <Image
      accessibilityLabel={current.label ? `${current.label} full screen` : "Attached image full screen"}
      testID="image-viewer-image"
      source={{ uri }}
      resizeMode="contain"
      style={[styles.image, { transform: [{ rotate: `${rotation}deg` }] }]}
    />
  );

  return (
    <Modal visible animationType="fade" statusBarTranslucent onRequestClose={onClose} supportedOrientations={["portrait", "landscape"]}>
      {/* A Modal is a separate native root on Android: gestures inside it need their own handler root. */}
      <GestureHandlerRootView style={styles.root}>
        <View accessibilityViewIsModal style={styles.root}>
          <GestureDetector gesture={gestures}>
            <Animated.View
              testID="image-viewer-stage"
              style={[styles.stage, zoomed]}
              onLayout={(event) => {
                stageW.value = event.nativeEvent.layout.width;
                stageH.value = event.nativeEvent.layout.height;
              }}
            >
              {/* Keyed by path: the next image mounts its own download and the last one's cache file is deleted. */}
              <View key={current.path} style={styles.image}>{renderMedia(current.path, renderImage)}</View>
            </Animated.View>
          </GestureDetector>
          <View style={[styles.top, { paddingTop: insets.top + 8, paddingLeft: insets.left + 12, paddingRight: insets.right + 12 }]}>
            <Control label="Close full screen" text="✕" onPress={onClose} />
            <Text accessibilityRole="header" numberOfLines={1} style={styles.counter}>
              {current.label ? `${current.label}  ` : ""}{index + 1} / {list.length}
            </Text>
          </View>
          <View style={[styles.bottom, { paddingBottom: insets.bottom + 8 }]}>
            <View style={styles.row}>
              {list.length > 1 ? <Control label="Previous attachment" text="‹" onPress={() => move(-1)} /> : null}
              <Control label="Rotate left" text="↶" onPress={() => rotate(-90)} />
              <Control label="Rotate right" text="↷" onPress={() => rotate(90)} />
              {list.length > 1 ? <Control label="Next attachment" text="›" onPress={() => move(1)} /> : null}
            </View>
            <View style={styles.row}>
              <Control label="Zoom out" text="−" onPress={() => zoomBy(1 / ZOOM_STEP)} />
              <Control label="Reset view" text="Reset" onPress={() => { setRotation(0); resetView(); }} />
              <Control label="Zoom in" text="+" onPress={() => zoomBy(ZOOM_STEP)} />
            </View>
          </View>
        </View>
      </GestureHandlerRootView>
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: BACKDROP },
  stage: { flex: 1, alignItems: "center", justifyContent: "center" },
  image: { width: "100%", height: "100%", alignItems: "center", justifyContent: "center" },
  top: { position: "absolute", top: 0, left: 0, right: 0, backgroundColor: SCRIM, paddingBottom: 8, flexDirection: "row", alignItems: "center", gap: 12 },
  bottom: { position: "absolute", bottom: 0, left: 0, right: 0, backgroundColor: SCRIM, paddingTop: 8, gap: 8 },
  row: { flexDirection: "row", justifyContent: "center", gap: 12 },
  button: { minWidth: 48, minHeight: 48, alignItems: "center", justifyContent: "center" },
  glyph: { color: ON_BACKDROP, fontSize: 26 },
  counter: { flex: 1, color: ON_BACKDROP, fontSize: 16 },
});
