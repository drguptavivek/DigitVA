/**
 * Per-screen Help of the phone app: one line on what the screen is for, a few things to do now, and the
 * server's full guide. The text is in the bundled string dictionaries (English and Hindi), so it works offline;
 * only "Open the full guide" needs the network. Guide slugs are the browser's (SCREEN_HELP_CONFIG).
 */
import { t, type StringKey } from "../i18n";

export type HelpScreen = "home" | "worklist" | "form" | "revision" | "settings" | "register";

/** The same pages the browser's contextual help opens (src/web/ContextualHelp.tsx); a test keeps them equal. */
export const HELP_SLUGS: Record<HelpScreen, string> = {
  home: "/help/getting-started",
  worklist: "/help/data-collection",
  form: "/help/data-collection",
  revision: "/help/data-collection",
  settings: "/help/getting-started",
  register: "/help/data-collection",
};

export function helpScreenFor(pathname: string): HelpScreen {
  switch (pathname) {
    case "/worklist":
    case "/case":
      return "worklist";
    case "/form":
      return "form";
    case "/revision":
      return "revision";
    case "/settings":
      return "settings";
    case "/register":
      return "register";
    default:
      return "home";
  }
}

export interface HelpContent {
  what: string;
  todo: string[];
  /** State-aware lines shown first: offline, unsent work. */
  state: string[];
  slug: string;
}

/** To-do lines about the server, Sync or re-enrolling: a standalone account has none of those. */
const ENROLLED_ONLY_TODO = new Set(["help_worklist_do2", "help_worklist_do3", "help_settings_do3", "help_register_do3"]);

export function helpContent(screen: HelpScreen, state: { offline?: boolean; unsent?: number; standalone?: boolean }): HelpContent {
  const key = (part: string) => `help_${screen}_${part}` as StringKey;
  const lines: string[] = [];
  if (state.offline) lines.push(t("helpOffline"));
  if (state.unsent) lines.push(t(state.standalone ? "helpUnsentStandalone" : "helpUnsent", { count: state.unsent }));
  const todo = [key("do1"), key("do2"), key("do3")].filter((item) => !(state.standalone && ENROLLED_ONLY_TODO.has(item)));
  return { what: t(key("what")), todo: todo.map((item) => t(item)), state: lines, slug: HELP_SLUGS[screen] };
}

/** The full guide on the enrolled server. */
export function helpGuideUrl(server: string, slug: string): string {
  return `${server.replace(/\/+$/, "")}${slug}`;
}
