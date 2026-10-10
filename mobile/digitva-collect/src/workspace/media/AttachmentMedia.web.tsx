import { useCallback, useEffect, useRef, useState } from "react";

import type { WorkspaceIdentity } from "../contracts";
import { AttachmentGallery } from "./AttachmentGallery.web";
import { attachmentMediaExtension, attachmentMediaKind, browserAudioSupported } from "./path";

const activeAudioElements = new Set<HTMLAudioElement>();

function pauseOtherAudio(current: HTMLAudioElement) {
  activeAudioElements.forEach((audio) => {
    if (audio !== current) audio.pause();
  });
  if (typeof document !== "undefined") {
    document.querySelectorAll<HTMLAudioElement>("audio[data-digitva-attachment]").forEach((audio) => {
      if (audio !== current) audio.pause();
    });
  }
  activeAudioElements.add(current);
}

function downloadName(path: string): string {
  return path.split("/").at(-1) || "attachment";
}

/** Render validated same-origin media through the browser's cookie session. */
export function AttachmentMedia({
  identity,
  attachmentPath,
}: {
  identity: WorkspaceIdentity;
  attachmentPath: string;
  userId?: string;
}) {
  const kind = attachmentMediaKind(attachmentPath);
  const extension = attachmentMediaExtension(attachmentPath);
  const [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  const [failedKey, setFailedKey] = useState("");
  const key = `${identity.mode}:${identity.vaSid}:${attachmentPath}`;
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const setAudioRef = useCallback((audio: HTMLAudioElement | null) => {
    if (!audio && audioRef.current) {
      audioRef.current.pause();
      activeAudioElements.delete(audioRef.current);
    }
    audioRef.current = audio;
  }, []);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const visibilityChanged = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => {
      document.removeEventListener("visibilitychange", visibilityChanged);
      const audio = audioRef.current;
      if (audio) {
        audio.pause();
        activeAudioElements.delete(audio);
      }
    };
  }, []);

  useEffect(() => {
    if (visible) return;
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      activeAudioElements.delete(audio);
    }
  }, [visible]);

  useEffect(() => () => {
    const audio = audioRef.current;
    if (audio) {
      audio.pause();
      activeAudioElements.delete(audio);
    }
  }, [key]);

  if (!kind && extension !== "pdf") return <p role="alert">Attachment unavailable.</p>;
  if (failedKey === key) {
    return kind === "audio"
      ? <a href={attachmentPath} download={downloadName(attachmentPath)}>Download audio attachment</a>
      : <p role="alert">Attachment unavailable.</p>;
  }
  if (!visible) return <p role="status">Loading attachment…</p>;
  if (kind === "image") {
    return <AttachmentGallery
      items={[{ label: "Attached image", value: attachmentPath, flip: false, info: false }]}
      label="Attached image"
      workspaceIdentity={`${identity.mode}:${identity.vaSid}`}
    />;
  }
  if (extension === "pdf") {
    return <a href={attachmentPath} download={downloadName(attachmentPath)}>Download document attachment</a>;
  }
  if (!browserAudioSupported(attachmentPath)) {
    return <a href={attachmentPath} download={downloadName(attachmentPath)}>Download audio attachment</a>;
  }
  return <audio
    ref={setAudioRef}
    data-digitva-attachment="true"
    controls
    preload="none"
    src={attachmentPath}
    aria-label="Attached audio"
    onPlay={(event) => pauseOtherAudio(event.currentTarget)}
    onPause={(event) => activeAudioElements.delete(event.currentTarget)}
    onEnded={(event) => activeAudioElements.delete(event.currentTarget)}
    onError={() => setFailedKey(key)}
  />;
}
