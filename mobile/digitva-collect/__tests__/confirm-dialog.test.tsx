import fs from "fs";
import path from "path";
import { Platform } from "react-native";
import { act, create, type ReactTestInstance } from "react-test-renderer";

import { ConfirmDialog } from "../src/ConfirmDialog";
import { buttonTone, ui } from "../src/theme";

const originalPlatform = Object.getOwnPropertyDescriptor(Platform, "OS");
afterEach(() => {
  if (originalPlatform) Object.defineProperty(Platform, "OS", originalPlatform);
});

function button(root: ReactTestInstance, label: string) {
  return root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label)[0];
}

async function show(props: Partial<React.ComponentProps<typeof ConfirmDialog>> = {}) {
  const onConfirm = jest.fn();
  const onCancel = jest.fn();
  let tree!: ReturnType<typeof create>;
  await act(async () => {
    tree = create(<ConfirmDialog title="Release this case?" message="Careful." confirmLabel="Release" destructive onConfirm={onConfirm} onCancel={onCancel} {...props} />);
  });
  return { tree, onConfirm, onCancel };
}

describe("ConfirmDialog", () => {
  test("confirm proceeds and cancel does not", async () => {
    const { tree, onConfirm, onCancel } = await show();
    expect(JSON.stringify(tree.toJSON())).toContain("Careful.");
    await act(async () => button(tree.root, "Cancel").props.onPress());
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
    await act(async () => button(tree.root, "Release").props.onPress());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  test("the confirm button is destructive-styled only when asked", async () => {
    const bg = async (destructive: boolean) => {
      const { tree } = await show({ destructive });
      const style = button(tree.root, "Release").props.style({ pressed: false }).flat(Infinity).filter(Boolean);
      return Object.assign({}, ...style).backgroundColor;
    };
    expect(await bg(true)).toBe(buttonTone(ui.light, "destructive").bg);
    expect(await bg(false)).toBe(buttonTone(ui.light, "default").bg);
  });

  test("on the web Escape cancels, and Tab stays inside the dialog", async () => {
    Object.defineProperty(Platform, "OS", { configurable: true, value: "web" });
    const listeners: Array<(e: unknown) => void> = [];
    (global as { document?: unknown }).document = {
      activeElement: null,
      addEventListener: (_: string, fn: (e: unknown) => void) => listeners.push(fn),
      removeEventListener: () => undefined,
    };
    const { onCancel } = await show();
    const key = (k: string) => {
      const e = { key: k, preventDefault: jest.fn() };
      listeners.forEach((fn) => fn(e));
      return e;
    };
    expect(key("Tab").preventDefault).toHaveBeenCalled();
    expect(onCancel).not.toHaveBeenCalled();
    key("Escape");
    expect(onCancel).toHaveBeenCalledTimes(1);
    delete (global as { document?: unknown }).document;
  });

  test("the dialog is labelled and modal for assistive tech", async () => {
    const { tree } = await show();
    const dialog = tree.root.findAll((n) => n.props.accessibilityViewIsModal)[0];
    expect(dialog.props.accessibilityLabel).toBe("Release this case?");
  });
});

describe("client policy", () => {
  test("no window.confirm, alert or prompt call is left in the Expo client", () => {
    const hits: string[] = [];
    const walk = (dir: string) => {
      for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (/\.(tsx?|jsx?)$/.test(entry.name) && /window\.(confirm|alert|prompt)\s*\(/.test(fs.readFileSync(full, "utf8"))) hits.push(full);
      }
    };
    walk(path.join(__dirname, "../src"));
    walk(path.join(__dirname, "../app"));
    expect(hits).toEqual([]);
  });
});
