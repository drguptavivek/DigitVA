/**
 * The interview page's address for reloading onto an existing draft. A new interview's address names only the
 * project and site, so reloading it as it is would start a second draft (and ask consent again).
 */
export function draftReloadUrl(href: string, draftId: string): string {
  const url = new URL(href);
  url.search = new URLSearchParams({ draftId }).toString();
  url.hash = "";
  return url.toString();
}
