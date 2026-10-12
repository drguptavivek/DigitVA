const VENDOR_CSS = [
  ["/static/vendors/roboto/roboto.css", "digitva-workspace-roboto"],
  ["/static/vendors/fontawesome/css/all.min.css", "digitva-workspace-fontawesome"],
] as const;

/** Adds the Flask-served Roboto and Font Awesome sheets once (by id); the shared header and the workspace both need them. */
export function ensureVendorCss(): void {
  if (typeof document === "undefined") return;
  for (const [href, id] of VENDOR_CSS) {
    if (document.getElementById(id)) continue;
    const link = document.createElement("link");
    link.id = id;
    link.rel = "stylesheet";
    link.href = href;
    document.head.appendChild(link);
  }
}
