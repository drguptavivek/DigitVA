import { act, create, type ReactTestInstance } from "react-test-renderer";

import type { DmSubmissionRow, UpstreamChangeDetails } from "../src/data/api";
import { rowActions } from "../src/web/data/DataTable";
import { UpstreamChangesDialog } from "../src/web/data/UpstreamChangesDialog";

const row = (over: Partial<DmSubmissionRow>) => ({ va_sid: "s1", workflow_state: "coded", revision_requested: false, ...over }) as DmSubmissionRow;
const actions = (r: DmSubmissionRow, manage: boolean) => rowActions(r, manage).map((a) => a.action);

describe("row actions", () => {
  test("a viewer can only open the read-only view", () => {
    expect(actions(row({}), false)).toEqual(["view"]);
    expect(actions(row({ workflow_state: "finalized_upstream_changed" }), false)).toEqual(["view"]);
  });

  test("a data manager edits in ODK, reviews upstream changes, or cancels a revision request", () => {
    expect(actions(row({}), true)).toEqual(["view", "edit"]);
    expect(actions(row({ workflow_state: "finalized_upstream_changed" }), true)).toEqual(["view", "changes"]);
    expect(actions(row({ workflow_state: "finalized_upstream_changed", revision_requested: true }), true)).toEqual(["view", "cancel"]);
  });
});

const details: UpstreamChangeDetails = {
  va_sid: "s1",
  changed_fields: [{ field_id: "age", field_label: "Age", category_code: null, subcategory_code: null, previous_value_display: "40", current_value_display: "<b>41</b>" }],
  non_substantive_changed_fields: [{ field_id: "meta", field_label: null, category_code: null, subcategory_code: null, previous_value_display: "a", current_value_display: "b" }],
  formatting_only_changed_fields: [],
  pii_changed: false,
};
const buttonOf = (root: ReactTestInstance, label: string) => root.findAll((n) => n.props.accessibilityRole === "button" && n.props.accessibilityLabel === label)[0];

describe("UpstreamChangesDialog", () => {
  const show = async (data: UpstreamChangeDetails | null) => {
    const onAccept = jest.fn();
    const onKeep = jest.fn();
    let tree!: ReturnType<typeof create>;
    await act(async () => {
      tree = create(<UpstreamChangesDialog formId="F-1" details={data} loading={false} error="" onAccept={onAccept} onKeep={onKeep} onClose={jest.fn()} />);
    });
    return { tree, onAccept, onKeep };
  };

  test("shows data and metadata tables as text, and offers both decisions", async () => {
    const { tree, onAccept, onKeep } = await show(details);
    const json = JSON.stringify(tree.toJSON());
    expect(json).toContain("Data changes");
    expect(json).toContain("Metadata changes");
    expect(json).not.toContain("Formatting-only changes");
    expect(json).toContain("<b>41</b>");
    await act(async () => buttonOf(tree.root, "Accept and recode").props.onPress());
    await act(async () => buttonOf(tree.root, "Keep current decision").props.onPress());
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(onKeep).toHaveBeenCalledTimes(1);
  });

  test("with no data change it says so; before the details arrive it offers no decision", async () => {
    expect(JSON.stringify((await show({ ...details, changed_fields: [] })).tree.toJSON())).toContain("No data changes were found for this update.");
    const { tree } = await show(null);
    expect(buttonOf(tree.root, "Accept and recode")).toBeUndefined();
    expect(buttonOf(tree.root, "Close")).toBeDefined();
  });
});
