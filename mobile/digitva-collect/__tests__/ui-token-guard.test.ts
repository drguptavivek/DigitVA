/**
 * Guard for the single token source (src/theme.ts, docs/current-state/doris-ui-tokens.md "ui-consistency").
 * Screens must take colours, radii and font sizes from the tokens; this scan fails with file:line for a
 * literal hex/rgb colour, a borderRadius or a fontSize that is not on the scale.
 */
import { readdirSync, readFileSync, statSync } from "fs";
import { join, relative } from "path";

const ROOT = join(__dirname, "..");
const SCAN = ["src/workspace", "src/web", "src/nativeRoutes", "src/ui.tsx"];
/** The theme definition files own the raw values. */
const THEME_FILES = ["src/theme.ts", "src/workspace/webPalette.ts", "src/whoWebTheme.ts"];

const RADIUS_SCALE = new Set([0, 4, 6, 8, 9999]);
const FONT_SCALE = new Set([12, 14, 16, 18, 20, 24, 26]);

/**
 * Colour literals that are deliberately outside the tokens: scrims, shadows, the logo plate and the lightbox.
 * A line is allowed when it is in the file and contains the text.
 */
const COLOUR_ALLOW: ReadonlyArray<{ file: string; text: string; why: string }> = [
  { file: "src/web/common.tsx", text: "rgba(0,0,0,0.45)", why: "navigation drawer scrim" },
  { file: "src/web/OrgTree.tsx", text: "rgba(0,0,0,0.45)", why: "people flyout scrim" },
  { file: "src/web/common.tsx", text: "shadowColor", why: "popover shadow" },
  { file: "src/web/InterviewScreen.tsx", text: "shadowColor", why: "popover shadow" },
  { file: "src/workspace/QueueScreen.tsx", text: "rgba(0,0,0,0.5)", why: "modal scrim" },
  { file: "src/web/caseFilters.tsx", text: "rgba(0,0,0,0.5)", why: "filter bottom-sheet scrim (the modal scrim)" },
  { file: "src/web/caseFilters.tsx", text: "rgba(0,0,0,0.35)", why: "filter side-panel scrim (lighter: the list stays readable beside it)" },
  { file: "src/web/DirectInterviewPanel.tsx", text: "rgba(0,0,0,0.5)", why: "area picker bottom-sheet scrim (the modal scrim)" },
  { file: "src/web/UsersScreen.tsx", text: "rgba(0,0,0,0.5)", why: "enrolment code dialog scrim (the modal scrim)" },
  { file: "src/workspace/AccountMenu.web.tsx", text: "rgba(0,0,0,0.28)", why: "menu shadow" },
  { file: "src/workspace/AccountMenu.web.tsx", text: "rgba(255,255,255,0.22)", why: "focus ring on the dark navigation bar" },
  { file: "src/web/AppHeader.web.tsx", text: "rgba(0,0,0,0.28)", why: "menu and sheet shadow" },
  { file: "src/web/AppHeader.web.tsx", text: "rgba(0,0,0,0.45)", why: "leave dialog scrim (the drawer scrim)" },
  { file: "src/workspace/WorkspaceLayout.web.tsx", text: "shadowColor", why: "card, drawer and notes shadows" },
  { file: "src/workspace/WorkspaceLayout.web.tsx", text: "rgba(0,0,0,", why: "drawer scrim and sticky-bar shadow" },
  { file: "src/workspace/WorkspaceLayout.web.tsx", text: "logo:", why: "logo plate stays white in both modes" },
  { file: "src/workspace/doris/IcdPickerModal.tsx", text: "rgba(17,24,39,0.62)", why: "picker modal scrim" },
  { file: "src/workspace/doris/CodeDetailsSheet.tsx", text: "rgba(17,24,39,0.62)", why: "ICD-11 details sheet scrim (the picker scrim)" },
  { file: "src/workspace/media/AttachmentGallery.web.tsx", text: "rgba(8, 13, 20, 0.94)", why: "lightbox scrim" },
  { file: "src/workspace/media/AttachmentGallery.web.tsx", text: "color: \"#fff\"", why: "lightbox controls sit on the dark scrim" },
  { file: "src/web/InterviewScreen.tsx", text: "stroke", why: "matches the literal stroke colours the WHO package paints on its SVG icons" }
];

const COLOUR = /#[0-9a-fA-F]{3,8}\b|rgba?\(/;

function files(path: string): string[] {
  const full = join(ROOT, path);
  if (!statSync(full).isDirectory()) return [path];
  return readdirSync(full).flatMap((name) => files(join(path, name)));
}

function offenders(): string[] {
  const found: string[] = [];
  for (const file of SCAN.flatMap(files).filter((f) => /\.tsx?$/.test(f) && !THEME_FILES.includes(f))) {
    readFileSync(join(ROOT, file), "utf8").split("\n").forEach((line, index) => {
      const at = `${relative("", file)}:${index + 1}`;
      if (COLOUR.test(line) && !COLOUR_ALLOW.some((rule) => rule.file === file && line.includes(rule.text))) {
        found.push(`${at} colour literal: ${line.trim().slice(0, 100)}`);
      }
      for (const match of line.matchAll(/\bborderRadius:\s*(\d+)/g)) {
        if (!RADIUS_SCALE.has(Number(match[1]))) found.push(`${at} borderRadius ${match[1]} is not on the radius scale (0, 4, 6, 8, 9999)`);
      }
      for (const match of line.matchAll(/\bfontSize:\s*(\d+)/g)) {
        if (!FONT_SCALE.has(Number(match[1]))) found.push(`${at} fontSize ${match[1]} is not on the text scale (12, 14, 16, 18, 20, 24, 26)`);
      }
    });
  }
  return found;
}

describe("ui token guard", () => {
  it("has no off-token colour, radius or font size in screens", () => {
    expect(offenders()).toEqual([]);
  });

  it("scans real files (the guard is not vacuous)", () => {
    expect(SCAN.flatMap(files).length).toBeGreaterThan(30);
  });
});
