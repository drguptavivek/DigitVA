/** Android throws "Invalid accessibility role value" for a role React Native does not know, which closes the app
 *  (2026-10-24: the confirm dialog's "alertdialog" crashed Delete draft on the phone). */
import { readFileSync, readdirSync, statSync } from "fs";
import { join } from "path";

const NATIVE_ROLES = new Set([
  "none", "button", "togglebutton", "link", "search", "image", "keyboardkey", "text", "adjustable", "imagebutton",
  "header", "summary", "alert", "checkbox", "combobox", "menu", "menubar", "menuitem", "progressbar", "radio",
  "radiogroup", "scrollbar", "spinbutton", "switch", "tab", "tabbar", "tablist", "timer", "list", "toolbar", "grid",
  "pager", "scrollview", "horizontalscrollview", "viewgroup", "webview", "drawerlayout", "slidingdrawer",
  "iconmenu", "dropdownlist",
]);

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "web" ? [] : files(path);
    return /\.tsx?$/.test(name) && !/\.web\.tsx?$/.test(name) ? [path] : [];
  });
}

test("every accessibilityRole literal in shared and native code is one Android accepts", () => {
  const found: string[] = [];
  for (const path of files(join(__dirname, "..", "src"))) {
    for (const match of readFileSync(path, "utf8").matchAll(/accessibilityRole[=:]\s*\{?\s*"([a-z]+)"/g)) {
      if (!NATIVE_ROLES.has(match[1])) found.push(`${path}: ${match[1]}`);
    }
  }
  expect(found.length + NATIVE_ROLES.size).toBeGreaterThan(0);
  expect(found).toEqual([]);
});
