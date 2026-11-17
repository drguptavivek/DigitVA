/**
 * Plays a saved recording: the questionnaire's `AudioPlayer` slot on the phone, offline coding's local
 * attachments, and online coding's server attachments (with the memory-only bearer `headers`).
 * A local uri is a short-lived plain copy made by the attachment services and deleted when the control lets go of it.
 */
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useEffect, useState } from "react";
import { Pressable, Text, View } from "react-native";

import { t } from "./i18n";
import { useTheme } from "./theme";
import { Button } from "./ui";

const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

export function AttachmentAudioPlayer({ uri, headers, accessibilityLabel, onError }: {
  uri: string;
  headers?: Record<string, string>;
  accessibilityLabel: string;
  onError: () => void;
}) {
  const theme = useTheme();
  const player = useAudioPlayer(headers ? { uri, headers } : { uri });
  const status = useAudioPlayerStatus(player);
  const [trackWidth, setTrackWidth] = useState(0);
  // At the end Android still reports the player as playing, so a bare seekTo(0) starts it again and it loops:
  // stop first, then rewind for the next Play.
  useEffect(() => {
    if (!status.didJustFinish) return;
    player.pause();
    void player.seekTo(0);
  }, [player, status.didJustFinish]);
  const duration = status.duration > 0 ? status.duration : 0;
  const progress = duration ? Math.min(1, status.currentTime / duration) : 0;
  const seek = (x: number) => {
    if (!duration || !trackWidth) return;
    try {
      void player.seekTo(Math.max(0, Math.min(1, x / trackWidth)) * duration);
    } catch {
      onError();
    }
  };
  return (
    <View accessibilityLabel={accessibilityLabel} style={{ flexDirection: "row", alignItems: "center", gap: 12, marginTop: 8 }}>
      <Button
        size="sm"
        kind="secondary"
        label={status.playing ? t("attachPause") : t("attachPlay")}
        onPress={() => {
          try {
            if (status.playing) player.pause();
            else player.play();
          } catch {
            onError();
          }
        }}
      />
      {/* Tap the track to jump there; the tall touch area wraps a thin bar. */}
      <Pressable
        accessibilityRole="adjustable"
        accessibilityLabel={t("attachSeek")}
        accessibilityValue={{ min: 0, max: Math.round(duration), now: Math.round(status.currentTime) }}
        disabled={!duration}
        onLayout={(event) => setTrackWidth(event.nativeEvent.layout.width)}
        onPress={(event) => seek(event.nativeEvent.locationX)}
        style={{ flex: 1, height: 44, justifyContent: "center" }}
      >
        <View style={{ height: 6, borderRadius: 3, backgroundColor: theme.ui.muted, overflow: "hidden" }}>
          <View style={{ width: `${progress * 100}%`, height: "100%", backgroundColor: theme.ui.primary }} />
        </View>
      </Pressable>
      <Text style={[theme.typography.body, { color: theme.colors.text }]}>
        {clock(status.currentTime)} / {clock(duration)}
      </Text>
    </View>
  );
}
