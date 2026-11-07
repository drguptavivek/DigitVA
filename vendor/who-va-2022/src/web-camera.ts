/**
 * Live-camera capture for desktop browsers, where `<input capture>` is ignored and
 * "Take photo" would only open the file picker.
 */
import { WHO_VA_BUILT_IN_UI_TRANSLATIONS } from "./languages/ui.js";
import { resolveUiMessages } from "./i18n.js";

/**
 * Shows a camera preview modal and resolves with the captured JPEG, `undefined` when the user
 * cancels, or `null` when no camera is usable (no mediaDevices, permission denied, no device)
 * so the caller can fall back to the file input. Every track is stopped on every exit.
 */
export async function captureWebCameraPhoto(): Promise<File | undefined | null> {
  if (typeof navigator === "undefined" || !navigator.mediaDevices?.getUserMedia) return null;
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
  } catch {
    return null;
  }
  const messages = resolveUiMessages(
    document.documentElement.lang || navigator.language || "en",
    WHO_VA_BUILT_IN_UI_TRANSLATIONS
  );
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;

  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", messages.cameraTitle);
    overlay.style.cssText =
      "position:fixed;inset:0;z-index:2147483647;background:rgba(0,0,0,.85);display:flex;" +
      "flex-direction:column;align-items:center;justify-content:center;gap:16px;padding:16px";
    const video = document.createElement("video");
    video.autoplay = true;
    video.muted = true;
    video.setAttribute("playsinline", "");
    video.srcObject = stream;
    video.style.cssText = "max-width:100%;max-height:75vh;background:#000";
    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:12px";
    const button = (label: string) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = label;
      b.setAttribute("aria-label", label);
      b.style.cssText = "font:inherit;font-size:16px;padding:10px 20px;min-height:44px;cursor:pointer";
      return b;
    };
    const capture = button(messages.cameraCapture);
    const cancel = button(messages.cameraCancel);
    bar.append(capture, cancel);
    overlay.append(video, bar);

    const finish = (result: File | undefined) => {
      stream.getTracks().forEach((track) => track.stop());
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      opener?.focus?.();
      resolve(result);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(undefined);
      } else if (event.key === "Tab") {
        // Keep focus inside the two-button dialog.
        event.preventDefault();
        (document.activeElement === capture ? cancel : capture).focus();
      }
    };
    cancel.addEventListener("click", () => finish(undefined));
    capture.addEventListener("click", () => {
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 1280;
      canvas.height = video.videoHeight || 720;
      canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob(
        (blob) =>
          finish(blob ? new File([blob], `camera-${Date.now()}.jpg`, { type: "image/jpeg" }) : undefined),
        "image/jpeg",
        0.92
      );
    });
    document.addEventListener("keydown", onKey, true);
    document.body.append(overlay);
    capture.focus();
  });
}
