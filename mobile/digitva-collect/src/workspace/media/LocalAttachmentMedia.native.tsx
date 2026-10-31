/**
 * A draft's own attachment in the offline coding workspace (Collect Plus): the category value
 * `digitva-local-attachment:<field_id>` names the field, whose answer holds the reference into the encrypted store
 * (src/attachmentStore.ts). Nothing is decrypted until the coder opens it, and only one is open at a time: it is shown
 * through a short-lived plain copy in the private cache, made and deleted as the questionnaire's own player does
 * (src/mediaFiles.ts writePlaybackCopy / removeFile; the folder is also wiped on lock). Nothing leaves the phone.
 */
import { useEffect, useState } from "react";
import { AppState, Image, Text, View } from "react-native";

import { AttachmentAudioPlayer } from "../../AttachmentAudioPlayer";
import { getAttachmentBytes, getAttachmentMeta, referenceId, type AttachmentKind } from "../../attachmentStore";
import type { Db } from "../../drafts";
import { t } from "../../i18n";
import { removeFile, writePlaybackCopy } from "../../mediaFiles";
import { Button, useUiStyles } from "../../ui";

/** Closes the attachment open now, so opening another removes its plain copy first. */
let closeOpen: (() => void) | undefined;

export function LocalAttachmentMedia({ db, draftId, reference, assertAllowed }: {
  db: Db;
  /** The open case: a stored file of any other draft is not shown. */
  draftId: string;
  /** The field's answer: the form engine's reference object or `who-va-attachment:<uuid>`. */
  reference: unknown;
  /** The case's access check, run before the stored bytes are read. */
  assertAllowed: () => Promise<void>;
}) {
  const styles = useUiStyles();
  const [open, setOpen] = useState(false);
  const [media, setMedia] = useState<{ uri: string; kind: AttachmentKind } | "missing" | null>(null);
  const [active, setActive] = useState(AppState.currentState !== "background" && AppState.currentState !== "inactive");

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => setActive(state === "active"));
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const close = () => setOpen(false);
    closeOpen?.();
    closeOpen = close;
    return () => { if (closeOpen === close) closeOpen = undefined; };
  }, [open]);

  useEffect(() => {
    // No plain copy while closed or in the background; it is made again on return.
    if (!open || !active) return undefined;
    let live = true;
    let uri: string | undefined;
    void (async () => {
      const id = referenceId(reference);
      if (!id) throw new Error("attachment_missing");
      await assertAllowed();
      const meta = await getAttachmentMeta(db, id);
      if (!meta || meta.draft_id !== draftId) throw new Error("attachment_missing");
      if (meta.kind === "document") {
        if (live) setMedia({ uri: "", kind: "document" });
        return;
      }
      const bytes = await getAttachmentBytes(db, id);
      if (!live) return;
      if (!bytes) throw new Error("attachment_missing");
      uri = writePlaybackCopy(meta.id, meta.ext, bytes);
      setMedia({ uri, kind: meta.kind });
    })().catch(() => { if (live) setMedia("missing"); });
    return () => {
      live = false;
      removeFile(uri);
      setMedia(null);
    };
  }, [active, assertAllowed, db, draftId, open, reference]);

  if (!open) return <Button kind="secondary" label={t("offlineAttachmentOpen")} onPress={() => setOpen(true)} />;
  const close = <Button kind="secondary" label={t("offlineAttachmentClose")} onPress={() => setOpen(false)} />;
  let body;
  if (media === "missing") body = <Text accessibilityRole="alert" style={styles.error}>{t("offlineAttachmentUnavailable")}</Text>;
  else if (!media) body = <Text style={styles.muted}>{t("offlineAttachmentLoading")}</Text>;
  else if (media.kind === "document") body = <Text style={styles.muted}>{t("offlineAttachmentDocument")}</Text>;
  else if (media.kind === "image") {
    body = <Image accessibilityLabel={t("offlineAttachedImage")} source={{ uri: media.uri }} resizeMode="contain" onError={() => setMedia("missing")} style={{ width: 280, height: 220 }} />;
  } else {
    body = <AttachmentAudioPlayer uri={media.uri} accessibilityLabel={t("offlineAttachedAudio")} onError={() => setMedia("missing")} />;
  }
  return <View style={{ gap: 8 }}>{body}{close}</View>;
}
