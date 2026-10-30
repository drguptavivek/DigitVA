/**
 * Plays a saved recording inside the questionnaire (the form engine's `AudioPlayer` slot on the phone).
 * The uri is a short-lived plain copy made by the attachment services and deleted when the control lets go of it.
 */
import { useAudioPlayer, useAudioPlayerStatus } from "expo-audio";
import { useEffect } from "react";
import { Text, View } from "react-native";

import { t } from "./i18n";
import { typography, useTheme } from "./theme";
import { Button } from "./ui";

const clock = (seconds: number) =>
  `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

export function AttachmentAudioPlayer({ uri, accessibilityLabel, onError }: { uri: string; accessibilityLabel: string; onError: () => void }) {
  const theme = useTheme();
  const player = useAudioPlayer({ uri });
  const status = useAudioPlayerStatus(player);
  // At the end Android still reports the player as playing, so a bare seekTo(0) starts it again and it loops:
  // stop first, then rewind for the next Play.
  useEffect(() => {
    if (!status.didJustFinish) return;
    player.pause();
    void player.seekTo(0);
  }, [player, status.didJustFinish]);
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
      <Text style={[typography.body, { color: theme.colors.text }]}>
        {clock(status.currentTime)} / {clock(status.duration)}
      </Text>
    </View>
  );
}
