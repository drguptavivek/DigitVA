import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useEffect, useRef, useState } from "react";
import { AppState, Image, Pressable, Text, View } from "react-native";

import { getAuthenticatedAttachmentSource } from "../../auth";
import type { WorkspaceIdentity } from "../contracts";
import { attachmentMediaKind } from "./path";

/** Load authenticated media from the API and release sources when its identity is no longer active. */
export function AttachmentMedia({
  identity,
  attachmentPath,
  userId,
}: {
  identity: WorkspaceIdentity;
  attachmentPath: string;
  userId?: string;
  bearerSource?: { server: string; token: string };
}) {
  const kind = attachmentMediaKind(attachmentPath);
  const player = useAudioPlayer(null);
  const status = useAudioPlayerStatus(player);
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
    player.pause();
    player.replace(null);
    if (!kind || !userId || !active) {
      if (!kind || !userId) setError(true);
      return () => {
        cancelled = true;
        player.pause();
        player.replace(null);
      };
    }

    void getAuthenticatedAttachmentSource(userId, attachmentPath).then((next) => {
      if (cancelled || currentKey.current !== key) return;
      setSource({ ...next, key });
      if (kind === "audio") player.replace(next);
    }).catch(() => {
      if (!cancelled) setError(true);
    });
    return () => {
      cancelled = true;
      player.pause();
      player.replace(null);
      setSource(null);
    };
  }, [active, attachmentPath, key, kind, player, userId]);

  if (error) return <Text accessibilityRole="alert">Attachment unavailable.</Text>;
  const currentSource = source?.key === key ? source : null;
  if (!currentSource) return <Text accessibilityRole="text">Loading attachment…</Text>;
  if (kind === "image") {
    return <Image accessibilityLabel="Attached image" source={currentSource} resizeMode="contain" onError={() => setError(true)} style={{ width: 280, height: 220 }} />;
  }
  return (
    <View>
      <Pressable accessibilityRole="button" accessibilityLabel={status.playing ? "Pause attached audio" : "Play attached audio"} onPress={() => status.playing ? player.pause() : player.play()}>
        <Text>{status.playing ? "Pause audio" : "Play audio"}</Text>
      </Pressable>
      {status.error ? <Text accessibilityRole="alert">Attachment unavailable.</Text> : null}
    </View>
  );
}
