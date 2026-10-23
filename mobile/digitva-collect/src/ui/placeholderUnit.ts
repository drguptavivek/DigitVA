/** A placeholder unit the server names for a sites-mode project; never shown. Pure, so native screens can share it with the browser lists. */
export function isInternalPlaceholderUnit(name: string | null | undefined): boolean {
  return !name || /^sites_in_project_/i.test(name.trim());
}
