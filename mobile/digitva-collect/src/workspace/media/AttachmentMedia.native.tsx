import { File } from "expo-file-system";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { AppState, Image, Pressable, Text, View } from "react-native";

import { getAuthenticatedAttachmentSource } from "../../auth";
import { removeFile } from "../../mediaFiles";
import { cacheFile, shareAndDelete } from "../../standalone/shareFile";
import type { WorkspaceIdentity } from "../contracts";
import { useImageViewer } from "./ImageViewer.native";
import { AttachmentAudioPlayer } from "../../AttachmentAudioPlayer";
import { attachmentMediaExtension, attachmentMediaKind } from "./path";


type AttachmentMediaProps = {
  identity: WorkspaceIdentity;
  attachmentPath: string;
  userId?: string;
  bearerSource?: { server: string; token: string };
  /** The case is a training case: its media is fetched with `training=1`. */
  training?: boolean;
  /** Full-screen viewer: draw the loaded image with this instead of the tappable inline image. */
  renderImage?: (uri: string) => ReactNode;
};

/** Load authenticated media from the API. A PDF is not shown inline: it opens from the share sheet. */
export function AttachmentMedia(props: AttachmentMediaProps) {
  if (attachmentMediaExtension(props.attachmentPath) === "pdf") {
    return <AttachmentDocument userId={props.userId} attachmentPath={props.attachmentPath} training={props.training} />;
  }
  return <AttachmentPlayback {...props} />;
}

/**
 * Downloads the PDF to a private cache file and hands it to the share sheet, which opens it in a PDF viewer.
 * shareAndDelete removes the copy afterwards, as the case export does with its file.
 */
function AttachmentDocument({ userId, attachmentPath, training }: { userId?: string; attachmentPath: string; training?: boolean }) {
  const [opening, setOpening] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!userId) return <Text accessibilityRole="alert">Attachment unavailable.</Text>;

  async function open(id: string) {
    setOpening(true);
    setFailed(false);
    const name = decodeURIComponent(attachmentPath.split("/").at(-1) ?? "attachment.pdf");
    const file = cacheFile(`attachment-${Date.now()}-${name}`);
    try {
      const source = await getAuthenticatedAttachmentSource(id, attachmentPath, training);
      await File.downloadFileAsync(source.uri, file, { headers: source.headers });
      await shareAndDelete(file, "application/pdf");
    } catch {
      setFailed(true);
    } finally {
      removeFile(file.uri);
      setOpening(false);
    }
  }

  return (
    <View>
      <Pressable accessibilityRole="button" accessibilityLabel="Open attached PDF" disabled={opening} onPress={() => void open(userId)}>
        <Text>{opening ? "Opening PDF…" : "Open PDF"}</Text>
      </Pressable>
      {failed ? <Text accessibilityRole="alert">Attachment unavailable.</Text> : null}
    </View>
  );
}

function AttachmentPlayback({ identity, attachmentPath, userId, training, renderImage }: AttachmentMediaProps) {
  const openViewer = useImageViewer();
  const kind = attachmentMediaKind(attachmentPath);
  const [source, setSource] = useState<{ key: string; uri: string; headers: Record<string, string> } | null>(null);
  const [error, setError] = useState(false);
  const [active, setActive] = useState(AppState.currentState !== "background" && AppState.currentState !== "inactive");
  const key = `${identity.mode}:${identity.vaSid}:${userId ?? ""}:${attachmentPath}`;
  const currentKey = useRef(key);
  currentKey.current = key;

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => setActive(state === "active"));
    const visibilityChanged = () => {
      if (typeof document !== "undefined") setActive(document.visibilityState === "visible");
    };
    if (typeof document !== "undefined") document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      subscription.remove();
      if (typeof document !== "undefined") document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setSource(null);
    setError(false);
    if (!kind || !userId || !active) {
      if (!kind || !userId) setError(true);
      return () => {
        cancelled = true;
      };
    }

    // RN's Android Image ignores source headers, so an image is downloaded with them to a private cache
    // file and shown from there; the file is removed on cleanup or when the result arrives too late.
    let cachedUri: string | undefined;
    void (async () => {
      const next = await getAuthenticatedAttachmentSource(userId, attachmentPath, training);
      if (kind === "image") {
        const file = cacheFile(`attachment-img-${Date.now()}-${Math.random().toString(36).slice(2)}.${attachmentMediaExtension(attachmentPath) ?? "jpg"}`);
        cachedUri = file.uri;
        await File.downloadFileAsync(next.uri, file, { headers: next.headers });
      }
      if (cancelled || currentKey.current !== key) {
        removeFile(cachedUri);
        return;
      }
      setSource({ uri: cachedUri ?? next.uri, headers: cachedUri ? {} : next.headers, key });
    })().catch(() => {
      removeFile(cachedUri);
      if (!cancelled) setError(true);
    });
    return () => {
      cancelled = true;
      setSource(null);
      removeFile(cachedUri);
    };
  }, [active, attachmentPath, key, kind, training, userId]);

  if (error) return <Text accessibilityRole="alert">Attachment unavailable.</Text>;
  const currentSource = source?.key === key ? source : null;
  if (!currentSource) return <Text accessibilityRole="text">Loading attachment…</Text>;
  if (kind === "image") {
    if (renderImage) return <>{renderImage(currentSource.uri)}</>;
    const image = <Image accessibilityLabel="Attached image" source={{ uri: currentSource.uri }} resizeMode="contain" onError={() => setError(true)} style={{ width: "100%", aspectRatio: 4 / 3 }} />;
    if (!openViewer) return image;
    return <Pressable accessibilityRole="imagebutton" accessibilityLabel="Open image full screen" onPress={() => openViewer(attachmentPath)}>{image}</Pressable>;
  }
  // The shared player (also the interview's and offline coding's) owns its expo-audio player, so it is
  // released when this source goes away, and it handles Android's end-of-clip loop.
  return (
    <AttachmentAudioPlayer
      uri={currentSource.uri}
      headers={currentSource.headers}
      accessibilityLabel="Attached audio"
      onError={() => setError(true)}
    />
  );
}
