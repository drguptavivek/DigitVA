/**
 * The phone's narration and documents gallery: the same `media_gallery` items as AttachmentGallery.web.tsx (the
 * narration image `imagenarr`, document images, PDFs and narration audio, bare or wrapped in an object or list),
 * one at a time with previous/next, and rotate for images. Every item is drawn by the screen's `renderMedia` slot,
 * so online media keeps the bearer transport (AttachmentMedia.native.tsx) and offline draft attachments keep the
 * encrypted store (LocalAttachmentMedia.native.tsx). Thumbnails and the pinch lightbox are web only.
 */
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Text, View } from "react-native";

import { Button, useUiStyles } from "../../ui";
import { collectPaths, type CategoryItem } from "./path";

export function AttachmentGallery({ items, label, workspaceIdentity, renderMedia }: {
  items: CategoryItem[];
  label: string;
  workspaceIdentity?: string;
  renderMedia?: (attachmentPath: string) => ReactNode;
}) {
  const styles = useUiStyles();
  const { attachments, truncated } = useMemo(() => collectPaths(items, true), [items]);
  const attachmentKey = attachments.map((item) => item.path).join("|");
  const [index, setIndex] = useState(0);
  const [rotations, setRotations] = useState<Record<string, number>>({});

  useEffect(() => {
    setIndex(0);
    setRotations({});
  }, [workspaceIdentity, label, attachmentKey]);

  const selectedIndex = Math.min(index, attachments.length - 1);
  const selected = attachments[selectedIndex];
  if (!renderMedia || !selected) return null;
  const rotation = rotations[selected.path] ?? 0;
  const move = (delta: number) => setIndex((current) => (current + delta + attachments.length) % attachments.length);
  const rotate = (delta: number) => setRotations((current) => ({ ...current, [selected.path]: rotation + delta }));

  return (
    <View accessibilityLabel={label} style={{ gap: 8 }}>
      <Text style={styles.muted}>{selected.label}{attachments.length > 1 ? `  ${selectedIndex + 1} / ${attachments.length}` : ""}</Text>
      {truncated ? <Text accessibilityRole="alert" style={styles.muted}>Some attachments were omitted because the attachment data exceeded the safe display limit.</Text> : null}
      {/* Keyed by path: a new item mounts its own player, and the last one's plain copy or audio is released. */}
      <View key={selected.path} testID="attachment-gallery-media" style={{ alignItems: "center", transform: [{ rotate: `${rotation}deg` }] }}>
        {renderMedia(selected.path)}
      </View>
      {selected.kind === "image" ? (
        <View style={{ flexDirection: "row", gap: 8, justifyContent: "center" }}>
          <Button kind="secondary" label="↶ Rotate left" onPress={() => rotate(-90)} />
          <Button kind="secondary" label="↷ Rotate right" onPress={() => rotate(90)} />
        </View>
      ) : null}
      {attachments.length > 1 ? (
        <View style={{ flexDirection: "row", gap: 8, justifyContent: "center" }}>
          <Button kind="secondary" label="Previous" accessibilityLabel="Previous attachment" onPress={() => move(-1)} />
          <Button kind="secondary" label="Next" accessibilityLabel="Next attachment" onPress={() => move(1)} />
        </View>
      ) : null}
    </View>
  );
}
