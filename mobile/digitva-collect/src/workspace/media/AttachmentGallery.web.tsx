import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CategoryPayload, JsonValue } from "../contracts";
import { attachmentMediaExtension, attachmentMediaKind, browserAudioSupported } from "./path";

type CategoryItem = CategoryPayload["subcategories"][number]["items"][number];
type GalleryAttachment = { path: string; label: string; kind: "image" | "audio" | "document" };

const BLUE = "#004687";
const BORDER = "#d9e0e7";
const MAX_NODES = 300;
const MAX_DEPTH = 8;

function collectPaths(items: CategoryItem[]): { attachments: GalleryAttachment[]; truncated: boolean } {
  const attachments: GalleryAttachment[] = [];
  const paths = new Set<string>();
  const seen = new WeakSet<object>();
  let nodes = 0;
  let truncated = false;

  const visit = (value: JsonValue, label: string, depth: number) => {
    if (nodes++ >= MAX_NODES || depth > MAX_DEPTH) {
      truncated = true;
      return;
    }
    if (typeof value === "string") {
      const extension = attachmentMediaExtension(value);
      const kind = attachmentMediaKind(value) ?? (extension === "pdf" ? "document" : null);
      if (kind && !paths.has(value)) {
        paths.add(value);
        attachments.push({ path: value, label, kind });
      }
      return;
    }
    if (!value || typeof value !== "object") return;
    if (seen.has(value)) return;
    seen.add(value);
    if (Array.isArray(value)) {
      value.forEach((item) => visit(item, label, depth + 1));
      return;
    }
    Object.entries(value).forEach(([key, child]) => visit(child, label || key.replace(/_/g, " "), depth + 1));
  };

  items.forEach((item) => visit(item.value, item.label, 0));
  return { attachments, truncated };
}

function downloadName(path: string): string {
  return path.split("/").at(-1) || "attachment";
}

function pauseOtherAudio(current: HTMLAudioElement) {
  document.querySelectorAll<HTMLAudioElement>("audio[data-digitva-attachment]").forEach((audio) => {
    if (audio !== current) audio.pause();
  });
}

function AudioAttachment({ path, label }: { path: string; label: string }) {
  const [failed, setFailed] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const setAudioRef = useCallback((audio: HTMLAudioElement | null) => {
    if (!audio && audioRef.current) audioRef.current.pause();
    audioRef.current = audio;
  }, []);
  useEffect(() => () => {
    audioRef.current?.pause();
    audioRef.current = null;
  }, []);
  if (!browserAudioSupported(path) || failed) {
    return <a href={path} download={downloadName(path)}>{`Download ${label || "audio attachment"}`}</a>;
  }
  return <audio
    ref={setAudioRef}
    data-digitva-attachment="true"
    controls
    preload="none"
    src={path}
    aria-label={label || "Attached audio"}
    onPlay={(event) => pauseOtherAudio(event.currentTarget)}
    onError={() => setFailed(true)}
  />;
}

/** Render HTMX's grouped attachment gallery in a phone-first browser layout. */
export function AttachmentGallery({
  items,
  label,
  visible = true,
  workspaceIdentity,
  renderMedia,
}: {
  items: CategoryItem[];
  label: string;
  visible?: boolean;
  workspaceIdentity?: string;
  renderMedia?: (attachmentPath: string) => React.ReactNode;
}) {
  const collection = useMemo(() => collectPaths(items), [items]);
  const { attachments, truncated } = collection;
  const attachmentKey = attachments.map((item) => item.path).join("|");
  const [index, setIndex] = useState(0);
  const [rotations, setRotations] = useState<Record<string, number>>({});
  const [failedImages, setFailedImages] = useState<Set<string>>(new Set());
  const [lightboxOpen, setLightboxOpen] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const lastFocus = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const dragStart = useRef<{ x: number; y: number; ox: number; oy: number } | null>(null);
  const pointers = useRef(new Map<number, { x: number; y: number }>());
  const pinchDistance = useRef<number | null>(null);
  const swipeStart = useRef<{ x: number; y: number } | null>(null);
  const selectedIndex = Math.min(index, Math.max(attachments.length - 1, 0));
  const selected = attachments[selectedIndex];
  const imageIndices = useMemo(() => attachments.reduce<number[]>((indices, attachment, attachmentIndex) => {
    if (attachment.kind === "image") indices.push(attachmentIndex);
    return indices;
  }, []), [attachments]);

  const closeLightbox = useCallback(() => {
    setLightboxOpen(false);
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    if (typeof window !== "undefined") window.setTimeout(() => lastFocus.current?.focus(), 0);
  }, []);

  const moveLightbox = useCallback((delta: number) => {
    if (!imageIndices.length) return;
    const currentImagePosition = Math.max(0, imageIndices.indexOf(selectedIndex));
    const nextImagePosition = (currentImagePosition + delta + imageIndices.length) % imageIndices.length;
    setIndex(imageIndices[nextImagePosition]);
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  }, [imageIndices, selectedIndex]);

  useEffect(() => {
    setIndex(0);
    setRotations({});
    setFailedImages(new Set());
    setLightboxOpen(false);
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  }, [workspaceIdentity, label, attachmentKey]);

  useEffect(() => {
    if (!lightboxOpen || typeof document === "undefined") return;
    closeRef.current?.focus();
  }, [lightboxOpen]);

  useEffect(() => {
    if (!lightboxOpen || typeof document === "undefined") return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeLightbox();
      if (event.key === "ArrowLeft") moveLightbox(-1);
      if (event.key === "ArrowRight") moveLightbox(1);
      if (event.key === "+" || event.key === "=") setZoom((current) => Math.min(6, current + 0.25));
      if (event.key === "-") setZoom((current) => Math.max(1, current - 0.25));
      if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>("button, [href], input, select, textarea, [tabindex]:not([tabindex='-1'])");
        if (!focusable?.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [closeLightbox, lightboxOpen, moveLightbox]);

  useEffect(() => {
    if (!lightboxOpen) return;
    setZoom(1);
    setOffset({ x: 0, y: 0 });
  }, [lightboxOpen, selected?.path]);

  if (!visible || !attachments.length || !selected) return null;
  const rotation = rotations[selected.path] ?? 0;
  const image = selected.kind === "image";
  const selectedImageFailed = failedImages.has(selected.path);
  const markImageFailed = (path: string) => setFailedImages((current) => new Set(current).add(path));
  const move = (delta: number) => {
    setIndex((current) => (current + delta + attachments.length) % attachments.length);
    if (lightboxOpen) {
      setZoom(1);
      setOffset({ x: 0, y: 0 });
    }
  };
  const rotate = (delta: number) => setRotations((current) => ({ ...current, [selected.path]: (current[selected.path] ?? 0) + delta }));
  const openLightbox = (event: React.MouseEvent<HTMLButtonElement>) => {
    lastFocus.current = event.currentTarget;
    setZoom(1);
    setOffset({ x: 0, y: 0 });
    setLightboxOpen(true);
  };
  const imageStyle: React.CSSProperties = {
    maxWidth: "100%",
    maxHeight: "min(62vh, 560px)",
    objectFit: "contain",
    transform: `translate(${offset.x}px, ${offset.y}px) scale(${zoom}) rotate(${rotation}deg)`,
    transformOrigin: "center center",
    userSelect: "none",
    touchAction: zoom > 1 ? "none" : "pan-y",
  };
  const pointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture?.(event.pointerId);
    if (pointers.current.size === 2) {
      const points = [...pointers.current.values()];
      pinchDistance.current = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      dragStart.current = null;
    } else if (zoom > 1) {
      dragStart.current = { x: event.clientX, y: event.clientY, ox: offset.x, oy: offset.y };
    } else {
      swipeStart.current = { x: event.clientX, y: event.clientY };
    }
  };
  const pointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    pointers.current.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.current.size === 2) {
      const points = [...pointers.current.values()];
      const nextDistance = Math.hypot(points[0].x - points[1].x, points[0].y - points[1].y);
      if (pinchDistance.current) {
        setZoom((current) => Math.min(6, Math.max(1, current * nextDistance / pinchDistance.current!)));
      }
      pinchDistance.current = nextDistance;
      return;
    }
    if (dragStart.current) {
      setOffset({ x: dragStart.current.ox + event.clientX - dragStart.current.x, y: dragStart.current.oy + event.clientY - dragStart.current.y });
    }
  };
  const pointerUp = (event: React.PointerEvent<HTMLDivElement>) => {
    const start = swipeStart.current;
    pointers.current.delete(event.pointerId);
    pinchDistance.current = null;
    dragStart.current = null;
    swipeStart.current = null;
    if (start && Math.abs(event.clientX - start.x) > 48 && Math.abs(event.clientY - start.y) < 72) {
      moveLightbox(event.clientX < start.x ? 1 : -1);
    }
  };

  return <section aria-label={label} style={styles.root}>
    <div style={styles.toolbar}>
      <span style={styles.badge}>{selected.label}</span>
      <span aria-live="polite" style={styles.counter}>{index + 1} / {attachments.length}</span>
    </div>
    {truncated ? <p role="status" style={styles.truncated}>Some attachments were omitted because the attachment data exceeded the safe display limit.</p> : null}
    {image ? <>
      <div style={styles.viewer}>
        {selectedImageFailed
          ? <a href={selected.path} download={downloadName(selected.path)}>Download image attachment</a>
          : <button type="button" onClick={openLightbox} aria-label={`Open ${selected.label || "attachment"} full screen`} style={styles.imageButton}>
            <img src={selected.path} alt={selected.label || "Attached image"} onError={() => markImageFailed(selected.path)} style={{ ...imageStyle, cursor: "zoom-in" }} />
          </button>}
        {attachments.length > 1 ? <>
          <button type="button" onClick={() => move(-1)} aria-label="Previous attachment" style={{ ...styles.arrow, left: 8 }}>‹</button>
          <button type="button" onClick={() => move(1)} aria-label="Next attachment" style={{ ...styles.arrow, right: 8 }}>›</button>
        </> : null}
      </div>
      <div style={styles.controls}>
        <button type="button" onClick={() => rotate(-90)} style={styles.control}>↶ Rotate left</button>
        <button type="button" onClick={() => rotate(90)} style={styles.control}>↷ Rotate right</button>
      </div>
    </> : selected.kind === "audio"
      ? <div style={styles.audio}>{renderMedia ? renderMedia(selected.path) : <AudioAttachment path={selected.path} label={selected.label} />}</div>
      : <div style={styles.audio}><a href={selected.path} download={downloadName(selected.path)}>Download {selected.label || "document attachment"}</a></div>}
    {attachments.length > 1 ? <div role="list" aria-label="Attachment thumbnails" style={styles.thumbnails}>
      {attachments.map((attachment, thumbnailIndex) => <button
        key={attachment.path}
        type="button"
        aria-label={`Show ${attachment.label || `attachment ${thumbnailIndex + 1}`}`}
        aria-current={thumbnailIndex === index}
        onClick={() => setIndex(thumbnailIndex)}
        style={{ ...styles.thumbnail, ...(thumbnailIndex === index ? styles.thumbnailActive : {}) }}
      >
        {attachment.kind === "image" && !failedImages.has(attachment.path)
          ? <img src={attachment.path} alt="" aria-hidden="true" loading="lazy" onError={() => markImageFailed(attachment.path)} style={styles.thumbnailImage} />
          : attachment.kind === "image" ? <span aria-hidden="true">▧</span> : attachment.kind === "audio" ? <span aria-hidden="true">♫</span> : <span aria-hidden="true">PDF</span>}
      </button>)}
    </div> : null}
    {lightboxOpen && image ? <div ref={dialogRef} role="dialog" aria-modal="true" aria-label={`${selected.label || "Attachment"} full screen`} style={styles.lightbox}>
      <button ref={closeRef} type="button" onClick={closeLightbox} aria-label="Close full screen" style={styles.close}>×</button>
      <div
        style={styles.lightboxViewport}
        onWheel={(event) => { event.preventDefault(); setZoom((current) => Math.min(6, Math.max(1, current + (event.deltaY < 0 ? 0.25 : -0.25)))); }}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={pointerUp}
        onPointerCancel={pointerUp}
      >
        <img src={selected.path} alt={selected.label || "Expanded attachment"} style={imageStyle} />
      </div>
      <div style={styles.lightboxControls}>
        <button type="button" onClick={() => moveLightbox(-1)} aria-label="Previous attachment" style={styles.control}>‹</button>
        <button type="button" onClick={() => rotate(-90)} aria-label="Rotate left" style={styles.control}>↶</button>
        <button type="button" onClick={() => setZoom((current) => Math.max(1, current - 0.25))} aria-label="Zoom out" style={styles.control}>−</button>
        <span style={styles.zoomLabel}>{Math.round(zoom * 100)}%</span>
        <button type="button" onClick={() => setZoom((current) => Math.min(6, current + 0.25))} aria-label="Zoom in" style={styles.control}>+</button>
        <button type="button" onClick={() => rotate(90)} aria-label="Rotate right" style={styles.control}>↷</button>
        <button type="button" onClick={() => moveLightbox(1)} aria-label="Next attachment" style={styles.control}>›</button>
      </div>
    </div> : null}
  </section>;
}

const styles: Record<string, React.CSSProperties> = {
  root: { display: "grid", gap: 12, minWidth: 0, width: "100%", overflow: "hidden" },
  toolbar: { alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "space-between" },
  badge: { background: BLUE, borderRadius: 999, color: "#fff", fontSize: 14, fontWeight: 700, maxWidth: "100%", overflow: "hidden", padding: "8px 14px", textOverflow: "ellipsis", whiteSpace: "nowrap" },
  counter: { color: "#596674", fontSize: 14 },
  truncated: { background: "#fff8e1", border: "1px solid #e0c36a", color: "#6a5311", fontSize: 14, margin: 0, padding: "8px 10px" },
  viewer: { alignItems: "center", background: "#f7f9fb", border: `1px solid ${BORDER}`, borderRadius: 4, display: "flex", justifyContent: "center", minHeight: 220, overflow: "hidden", padding: 12, position: "relative" },
  imageButton: { alignItems: "center", background: "transparent", border: 0, cursor: "zoom-in", display: "flex", justifyContent: "center", maxWidth: "100%", minHeight: 196, padding: 0 },
  arrow: { alignItems: "center", background: BLUE, border: 0, borderRadius: 999, color: "#fff", cursor: "pointer", display: "flex", fontSize: 30, height: 44, justifyContent: "center", lineHeight: 1, position: "absolute", top: "50%", transform: "translateY(-50%)", width: 44 },
  controls: { display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center" },
  control: { alignItems: "center", background: "#fff", border: `1px solid ${BORDER}`, borderRadius: 4, color: BLUE, cursor: "pointer", display: "inline-flex", fontSize: 14, fontWeight: 700, minHeight: 44, minWidth: 44, padding: "8px 12px" },
  audio: { minWidth: 0, width: "100%" },
  thumbnails: { display: "flex", gap: 8, maxWidth: "100%", overflowX: "auto", padding: "2px 0 4px" },
  thumbnail: { alignItems: "center", background: "#fff", border: `2px solid transparent`, borderRadius: 4, color: BLUE, cursor: "pointer", display: "flex", flex: "0 0 64px", height: 52, justifyContent: "center", minHeight: 44, minWidth: 44, overflow: "hidden", padding: 2 },
  thumbnailActive: { borderColor: BLUE },
  thumbnailImage: { height: "100%", objectFit: "cover", width: "100%" },
  lightbox: { alignItems: "center", background: "rgba(8, 13, 20, 0.94)", display: "flex", flexDirection: "column", inset: 0, justifyContent: "center", padding: 16, position: "fixed", zIndex: 2000 },
  close: { alignItems: "center", background: "#fff", border: 0, borderRadius: 999, color: "#111", cursor: "pointer", display: "flex", fontSize: 28, height: 44, justifyContent: "center", position: "absolute", right: 16, top: 16, width: 44, zIndex: 1 },
  lightboxViewport: { alignItems: "center", display: "flex", flex: 1, justifyContent: "center", maxWidth: "100%", overflow: "hidden", touchAction: "none", width: "100%" },
  lightboxControls: { alignItems: "center", display: "flex", flexWrap: "wrap", gap: 8, justifyContent: "center", padding: 8 },
  zoomLabel: { color: "#fff", minWidth: 52, textAlign: "center" },
};
