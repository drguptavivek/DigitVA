/** Settings' backup section: the actions are rows of the section's grouped card, never tint buttons in a nested card. */
import { act, create, type ReactTestRenderer } from "react-test-renderer";

jest.mock("expo-document-picker", () => ({ getDocumentAsync: jest.fn() }));
jest.mock("react-native-safe-area-context", () => ({ SafeAreaView: "SafeAreaView", useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }) }));
jest.mock("../src/standalone/backup", () => ({ BackupError: class BackupError extends Error {}, backupAndShare: jest.fn(), passphraseValid: () => true, restoreBackup: jest.fn() }));
jest.mock("../src/standalone/export", () => ({ exportAndShare: jest.fn() }));
jest.mock("../src/standalone/shareFile", () => ({ sweepExportLeftovers: () => undefined }));

import en from "../src/strings/en.json";
import { DataActions } from "../src/standalone/DataActions";
import { Button, ListRow, PasswordInput } from "../src/ui";

async function render(exportAllowed: boolean): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(<DataActions db={{} as never} userId="u1" exportAllowed={exportAllowed} onChanged={() => undefined} />); });
  return tree;
}

it("draws Back up and Restore as two chevron rows, with no button until one is opened", async () => {
  const tree = await render(false);
  const rows = tree.root.findAllByType(ListRow);
  expect(rows.map((row) => row.props.label)).toEqual([en.dataBackup, en.dataRestore]);
  expect(rows.every((row) => typeof row.props.onPress === "function" && row.props.action === undefined)).toBe(true);
  expect(tree.root.findAllByType(Button)).toHaveLength(0);
  await act(async () => { rows[0].props.onPress(); });
  // The open action's fields come under the rows, inside the same card.
  expect(tree.root.findAllByType(PasswordInput)).toHaveLength(2);
  expect(tree.root.findAllByType(PasswordInput).every((input) => input.props.onCard === true)).toBe(true);
  expect(tree.root.findAllByType(Button).map((button) => button.props.label)).toEqual([en.dataBackup, en.dataClose]);
});

it("adds the Export row first for a standalone account", async () => {
  const tree = await render(true);
  expect(tree.root.findAllByType(ListRow).map((row) => row.props.label)).toEqual([en.dataExport, en.dataBackup, en.dataRestore]);
});
