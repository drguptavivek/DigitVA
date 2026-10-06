import { useEffect, useState } from "react";

import type { WorkspaceIdentity } from "../contracts";
import { attachmentMediaKind } from "./path";

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
  const [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState === "visible");
  const [failedKey, setFailedKey] = useState("");
  const key = `${identity.mode}:${identity.vaSid}:${attachmentPath}`;

  useEffect(() => {
    if (typeof document === "undefined") return;
    const visibilityChanged = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", visibilityChanged);
    return () => document.removeEventListener("visibilitychange", visibilityChanged);
  }, []);

  if (!kind || failedKey === key) return <p role="alert">Attachment unavailable.</p>;
  if (!visible) return <p role="status">Loading attachment…</p>;
  return kind === "image"
    ? <img src={attachmentPath} alt="Attached image" onError={() => setFailedKey(key)} />
    : <audio controls preload="none" src={attachmentPath} aria-label="Attached audio" onError={() => setFailedKey(key)} />;
}
