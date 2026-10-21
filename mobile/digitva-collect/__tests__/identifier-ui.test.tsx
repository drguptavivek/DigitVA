import React from "react";
import { Text, TextInput } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

async function render(element: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => { tree = create(element); });
  return tree;
}

const mockBootstrap = { csrf: { header: "X-CSRFToken", token: "csrf" }, links: { intakeCases: "/api/v1/intake/cases" } };
jest.mock("../src/AppState", () => ({ useAppState: () => ({ bootstrap: mockBootstrap }) }));
jest.mock("../src/i18n", () => ({
  t: (key: string, v: Record<string, string | number> = {}) => key + Object.values(v).map((x) => `|${x}`).join(""),
}));
jest.mock("../src/ui", () => ({
  Button: ({ label, onPress, disabled }: { label: string; onPress: () => void; disabled?: boolean }) =>
    <button data-label={label} data-disabled={disabled ? "1" : ""} onClick={onPress} />,
  useUiStyles: () => ({ error: {}, muted: {}, input: {}, card: {}, text: {}, row: {}, fieldLabel: {}, headline: {} }),
}));

import * as api from "../src/api";
import { IdentifierFields } from "../src/IdentifierFields";
import { clearIdentifierTypeCache, type IdentifierType } from "../src/identifiers";
import * as identifiers from "../src/identifiers";
import { AddIdentifierAction, IdentifierFacts } from "../src/web/CaseIdentifiers";

const TYPE: IdentifierType = {
  code: "mccd", label: "MCCD number", min_length: 5, max_length: 12, char_type: "letters_digits", pattern: "MCCD[0-9]+",
  example: "MCCD123", required_at_report: true, sort_order: 1,
};

const text = (tree: ReactTestRenderer) => JSON.stringify(tree.toJSON());
const settle = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

afterEach(() => { jest.restoreAllMocks(); clearIdentifierTypeCache(); });

describe("IdentifierFields", () => {
  it("renders a monospaced, uncorrected input with the example hint and a required marker", async () => {
    const tree = await render(<IdentifierFields types={[TYPE]} values={{}} onChange={jest.fn()} />);
    const input = tree.root.findByType(TextInput);
    expect(input.props.autoCapitalize).toBe("characters");
    expect(input.props.autoCorrect).toBe(false);
    expect(input.props.spellCheck).toBe(false);
    expect(input.props.accessibilityLabel).toBe("idRequiredA11y|MCCD number");
    const style = ([] as object[]).concat(input.props.style).flat() as Array<Record<string, unknown>>;
    expect(String(style.find((s) => s && s.fontFamily)?.fontFamily)).toMatch(/mono|Menlo|Consolas/i);
    expect(text(tree)).toContain("MCCD number *");
    expect(text(tree)).toContain("idExample|MCCD123");
  });

  it("upper-cases what is typed", async () => {
    const onChange = jest.fn();
    const tree = await render(<IdentifierFields types={[TYPE]} values={{}} onChange={onChange} />);
    await act(async () => tree.root.findByType(TextInput).props.onChangeText("mccd12"));
    expect(onChange).toHaveBeenCalledWith("mccd", "MCCD12");
  });

  it("puts the caret after the typed character when typing in the middle, from the pre-keystroke selection", async () => {
    let value = "MCCD12";
    const onChange = jest.fn((_code: string, next: string) => { value = next; });
    const tree = await render(<IdentifierFields types={[TYPE]} values={{ mccd: value }} onChange={onChange} />);
    const input = () => tree.root.findByType(TextInput);
    const select = (start: number) => act(async () => input().props.onSelectionChange({ nativeEvent: { selection: { start, end: start } } }));
    // The caret sits at 3; "x" is typed there. onChangeText fires before the new selection event.
    await select(3);
    await act(async () => input().props.onChangeText("MCCxD12"));
    expect(value).toBe("MCCXD12");
    expect(input().props.selection).toEqual({ start: 4, end: 4 });
    // The platform's own selection event releases the control.
    await select(4);
    expect(input().props.selection).toBeUndefined();
    // No change of text: the caret is never forced.
    await act(async () => input().props.onChangeText("MCCXD123"));
    expect(input().props.selection).toBeUndefined();
  });

  it("counts a leading space and a ß that becomes SS in the caret", async () => {
    const onChange = jest.fn();
    const tree = await render(<IdentifierFields types={[TYPE]} values={{ mccd: "AB" }} onChange={onChange} />);
    const input = () => tree.root.findByType(TextInput);
    await act(async () => input().props.onSelectionChange({ nativeEvent: { selection: { start: 0, end: 0 } } }));
    await act(async () => input().props.onChangeText(" AB"));
    expect(onChange).toHaveBeenLastCalledWith("mccd", "AB");
    expect(input().props.selection).toEqual({ start: 0, end: 0 });
    await act(async () => input().props.onSelectionChange({ nativeEvent: { selection: { start: 1, end: 1 } } }));
    await act(async () => input().props.onChangeText("AßB"));
    expect(onChange).toHaveBeenLastCalledWith("mccd", "ASSB");
    expect(input().props.selection).toEqual({ start: 3, end: 3 });
  });

  it("shows the rule broken for length, character type and pattern, and nothing for a good value", async () => {
    const show = async (value: string) => text(await render(<IdentifierFields types={[TYPE]} values={{ mccd: value }} onChange={jest.fn()} />));
    expect(await show("MCC")).toContain("idErrLength|MCCD number|5|12");
    expect(await show("MCCD-12")).toContain("idErrLettersDigits");
    expect(await show("ABCDE1")).toContain("idErrPatternExample|MCCD number|MCCD123");
    expect(await show("MCCD123")).not.toContain("idErr");
    const digits = { ...TYPE, char_type: "digits" as const, pattern: null };
    expect(text(await render(<IdentifierFields types={[digits]} values={{ mccd: "12a45" }} onChange={jest.fn()} />))).toContain("idErrDigits");
  });

  it("shows a server refusal under the field", async () => {
    const tree = await render(<IdentifierFields types={[TYPE]} values={{ mccd: "MCCD123" }} errors={{ mccd: "MCCD number must look like MCCD123" }} onChange={jest.fn()} />);
    expect(text(tree)).toContain("MCCD number must look like MCCD123");
  });

  it("shows a duplicate warning with Continue and Edit that only call back", async () => {
    const onContinue = jest.fn();
    const onEdit = jest.fn();
    const tree = await render(<IdentifierFields types={[TYPE]} values={{ mccd: "MCCD123" }} warnings={{ mccd: "Already on another case." }} onChange={jest.fn()} onContinue={onContinue} onEdit={onEdit} />);
    expect(text(tree)).toContain("Already on another case.");
    await act(async () => tree.root.findByProps({ "data-label": "idWarnContinue" }).props.onClick());
    await act(async () => tree.root.findByProps({ "data-label": "idWarnEdit" }).props.onClick());
    expect(onContinue).toHaveBeenCalledWith("mccd");
    expect(onEdit).toHaveBeenCalledWith("mccd");
  });

  it("renders nothing for a project without types", async () => {
    expect((await render(<IdentifierFields types={[]} values={{}} onChange={jest.fn()} />)).toJSON()).toBeNull();
  });
});

describe("IdentifierFacts", () => {
  const entries = [
    { code: "mccd", label: "MCCD number", value: "MCCD123" },
    { code: "cert", label: "Certificate", value: null },
  ];
  it("shows a value viewer the numbers, label first, and nothing for a missing one on a card", async () => {
    const out = text(await render(<IdentifierFacts identifiers={entries} variant="card" />));
    expect(out).toContain("MCCD number");
    expect(out).toContain("MCCD123");
    expect(out).not.toContain("Certificate");
  });
  it("says Not yet issued on the detail", async () => {
    const out = text(await render(<IdentifierFacts identifiers={entries} variant="detail" />));
    expect(out).toContain("Certificate");
    expect(out).toContain("idNotYetIssued");
  });
  it("shows a badge-only viewer recorded or missing per type, never a value", async () => {
    const out = text(await render(<IdentifierFacts identifiers={[{ code: "mccd", label: "MCCD number", present: true }, { code: "cert", label: "Certificate", present: false }]} variant="card" />));
    expect(out).toContain("idBadgeRecorded|MCCD number");
    expect(out).toContain("idBadgeMissing|Certificate");
  });
  it("shows each entry on its own terms: a value, Not yet issued, or recorded when the server sent no value", async () => {
    const out = text(await render(<IdentifierFacts variant="detail" identifiers={[
      { code: "mccd", label: "MCCD number", value: "MCCD123" },
      { code: "cert", label: "Certificate", value: null },
      { code: "bad", label: "Undecryptable", present: true },
    ]} />));
    expect(out).toContain("MCCD123");
    expect(out).toContain("idNotYetIssued");
    expect(out).toContain("idBadgeRecorded|Undecryptable");
  });
  it("renders the detail with only missing numbers, and nothing on a card", async () => {
    const missing = [{ code: "cert", label: "Certificate", value: null }];
    expect(text(await render(<IdentifierFacts identifiers={missing} variant="detail" />))).toContain("idNotYetIssued");
    expect((await render(<IdentifierFacts identifiers={missing} variant="card" />)).toJSON()).toBeNull();
  });
  it("renders nothing without identifiers", async () => {
    expect((await render(<IdentifierFacts identifiers={undefined} variant="card" />)).toJSON()).toBeNull();
    expect((await render(<IdentifierFacts identifiers={[]} variant="detail" />)).toJSON()).toBeNull();
  });
});

describe("AddIdentifierAction", () => {
  const row = { death_id: "d1", project_id: "P1", updated_at: "2026-10-21T10:00:00Z", identifiers: [] as never[], can_edit_identifiers: true };
  const open = async (props: Partial<typeof row> & { onChanged?: () => void } = {}) => {
    jest.spyOn(identifiers, "loadIdentifierTypes").mockResolvedValue([{ ...TYPE, required_at_report: false, pattern: null, char_type: null }]);
    const onChanged = props.onChanged ?? jest.fn();
    const tree = await render(<AddIdentifierAction row={{ ...row, ...props }} onChanged={onChanged} />);
    await act(async () => tree.root.findByProps({ "data-label": "idAddAction" }).props.onClick());
    await settle();
    return { tree, onChanged };
  };
  const type = (tree: ReactTestRenderer, value: string) => act(async () => tree.root.findByType(TextInput).props.onChangeText(value));
  const save = async (tree: ReactTestRenderer) => { await act(async () => tree.root.findByProps({ "data-label": "save" }).props.onClick()); await settle(); };

  it("is absent unless the server flag is true", async () => {
    jest.spyOn(identifiers, "loadIdentifierTypes").mockResolvedValue([TYPE]);
    expect((await render(<AddIdentifierAction row={{ ...row, can_edit_identifiers: undefined }} onChanged={jest.fn()} />)).toJSON()).toBeNull();
    expect((await render(<AddIdentifierAction row={{ ...row, can_edit_identifiers: false }} onChanged={jest.fn()} />)).toJSON()).toBeNull();
    expect((await render(<AddIdentifierAction row={row} onChanged={jest.fn()} />)).toJSON()).not.toBeNull();
  });

  it("says the types could not be loaded and keeps the button hidden", async () => {
    jest.spyOn(identifiers, "loadIdentifierTypes").mockRejectedValue(new Error("403"));
    const tree = await render(<AddIdentifierAction row={row} onChanged={jest.fn()} />);
    await settle();
    expect(text(tree)).toContain("idTypesLoadFailed");
    expect(text(tree)).not.toContain("idNoTypes");
    expect(tree.root.findAllByProps({ "data-label": "idAddAction" })).toHaveLength(0);
  });

  it("hides the button for a project without types", async () => {
    jest.spyOn(identifiers, "loadIdentifierTypes").mockResolvedValue([]);
    const tree = await render(<AddIdentifierAction row={row} onChanged={jest.fn()} />);
    await settle();
    expect(tree.toJSON()).toBeNull();
  });

  it("saves through PUT with if_updated_at and the CSRF token, then reloads and closes", async () => {
    const put = jest.spyOn(api, "requestClientJson").mockResolvedValue({ case: { updated_at: "2026-10-21T10:01:00Z" } } as never);
    const { tree, onChanged } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(put).toHaveBeenCalledWith("/api/v1/intake/cases/d1/identifiers", {
      method: "PUT", json: { identifiers: { mccd: "MCCD123" }, if_updated_at: "2026-10-21T10:00:00Z" }, csrf: mockBootstrap.csrf,
    });
    expect(onChanged).toHaveBeenCalled();
    expect(tree.root.findAllByProps({ testID: "identifier-panel" })).toHaveLength(0);
  });

  it("keeps the panel on a duplicate warning; Continue closes it", async () => {
    jest.spyOn(api, "requestClientJson").mockResolvedValue({
      case: {}, warnings: [{ code: "identifier_in_use", field: "identifiers.mccd", message: "Already on another case." }],
    } as never);
    const { tree } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(text(tree)).toContain("Already on another case.");
    await act(async () => tree.root.findByProps({ "data-label": "idWarnContinue" }).props.onClick());
    expect(tree.root.findAllByProps({ testID: "identifier-panel" })).toHaveLength(0);
  });

  it("drops the saved message when Edit follows a duplicate warning", async () => {
    jest.spyOn(api, "requestClientJson").mockResolvedValue({
      case: {}, warnings: [{ code: "identifier_in_use", field: "identifiers.mccd", message: "Already on another case." }],
    } as never);
    const { tree } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(text(tree)).toContain("idSaved");
    await act(async () => tree.root.findByProps({ "data-label": "idWarnEdit" }).props.onClick());
    expect(text(tree)).not.toContain("idSaved");
    expect(text(tree)).not.toContain("Already on another case.");
  });

  it("reloads on death_stale and says why", async () => {
    jest.spyOn(api, "requestClientJson").mockRejectedValue(new api.ApiError(409, "death_stale"));
    const { tree, onChanged } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(onChanged).toHaveBeenCalled();
  });

  it("explains a closed case and keeps the panel", async () => {
    jest.spyOn(api, "requestClientJson").mockRejectedValue(new api.ApiError(409, "case_closed"));
    const { tree, onChanged } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(text(tree)).toContain("idCaseClosed");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("shows a 400 refusal under the named field", async () => {
    jest.spyOn(api, "requestClientJson").mockRejectedValue(new api.ApiError(400, "invalid_request", undefined, undefined, { error: "MCCD number must look like MCCD123", fields: ["identifiers.mccd"] }));
    const { tree } = await open();
    await type(tree, "mccd123");
    await save(tree);
    expect(text(tree)).toContain("MCCD number must look like MCCD123");
  });

  it("prefills the entries that have values when another entry arrived without one", async () => {
    const put = jest.spyOn(api, "requestClientJson").mockResolvedValue({ case: {} } as never);
    const { tree } = await open({ identifiers: [
      { code: "mccd", label: "MCCD number", value: "MCCD123" }, { code: "cert", label: "Certificate", present: true },
    ] as never });
    expect(tree.root.findByType(TextInput).props.value).toBe("MCCD123");
    await save(tree);
    expect(put).not.toHaveBeenCalled();
  });

  it("sends only changed codes for a value viewer and never a clear for a badge-only viewer's empty input", async () => {
    const put = jest.spyOn(api, "requestClientJson").mockResolvedValue({ case: {} } as never);
    const { tree } = await open({ identifiers: [{ code: "mccd", label: "MCCD number", value: "MCCD123" }] as never });
    expect(tree.root.findByType(TextInput).props.value).toBe("MCCD123");
    await save(tree);
    expect(put).not.toHaveBeenCalled();
    const badge = await open({ identifiers: [{ code: "mccd", label: "MCCD number", present: true }] as never });
    expect(badge.tree.root.findByType(TextInput).props.value).toBe("");
    await save(badge.tree);
    expect(put).not.toHaveBeenCalled();
  });
});
