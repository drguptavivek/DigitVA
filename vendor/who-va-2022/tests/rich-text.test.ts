import { describe, expect, it } from "vitest";

import { whoVa2022Instrument } from "../src/instrument.js";
import { parseRichText, richTextToPlain } from "../src/ui/rich-text.js";

describe("inline markup in labels, hints and guidance", () => {
  it("returns a single plain span when there is no markup", () => {
    expect(parseRichText("Record the name")).toEqual([{ text: "Record the name" }]);
  });

  it("always returns at least one span", () => {
    expect(parseRichText(undefined)).toEqual([{ text: "" }]);
    expect(parseRichText("")).toEqual([{ text: "" }]);
  });

  it("renders the coloured span the WHO guidance uses", () => {
    const spans = parseRichText('<span style="color:blue">Record the name here.</span>');
    expect(spans).toEqual([{ color: "blue", text: "Record the name here." }]);
  });

  it("keeps text outside the span unstyled", () => {
    const spans = parseRichText('Before <span style="color:#336699">inside</span> after');
    expect(spans).toEqual([
      { text: "Before " },
      { color: "#336699", text: "inside" },
      { text: " after" }
    ]);
  });

  it("reads background-color alongside color", () => {
    const [span] = parseRichText('<span style="color: red; background-color: #eee">x</span>');
    expect(span).toMatchObject({ color: "red", backgroundColor: "#eee", text: "x" });
  });

  it("ignores a style value that is not a colour", () => {
    const [span] = parseRichText('<span style="color: url(javascript:alert(1))">x</span>');
    expect(span).toEqual({ text: "x" });
  });

  it("handles bold and italic in both markdown spellings", () => {
    expect(parseRichText("**loud**")).toEqual([{ bold: true, text: "loud" }]);
    expect(parseRichText("__loud__")).toEqual([{ bold: true, text: "loud" }]);
    expect(parseRichText("*soft*")).toEqual([{ italic: true, text: "soft" }]);
    expect(parseRichText("_soft_")).toEqual([{ italic: true, text: "soft" }]);
  });

  it("leaves an unmatched emphasis marker as literal text", () => {
    expect(richTextToPlain("2 * 3 = 6")).toBe("2 * 3 = 6");
  });

  it("handles the html emphasis tags", () => {
    expect(parseRichText("<b>a</b><i>b</i><u>c</u>")).toEqual([
      { bold: true, text: "a" },
      { italic: true, text: "b" },
      { underline: true, text: "c" }
    ]);
  });

  it("turns <br> into a line break", () => {
    expect(richTextToPlain("one<br>two")).toBe("one\ntwo");
  });

  it("nests styles", () => {
    const spans = parseRichText('<span style="color:blue">blue <b>and bold</b></span>');
    expect(spans).toEqual([
      { color: "blue", text: "blue " },
      { color: "blue", bold: true, text: "and bold" }
    ]);
  });

  it("extracts links", () => {
    expect(parseRichText("see [the guide](https://example.org/g)")).toEqual([
      { text: "see " },
      { text: "the guide", href: "https://example.org/g", underline: true }
    ]);
  });

  it("decodes the entities the old plain-text path handled", () => {
    expect(richTextToPlain("Tom &amp; Jerry")).toBe("Tom & Jerry");
    expect(richTextToPlain("a&nbsp;b")).toBe("a\u00a0b");
  });

  it("does not manufacture a tag from escaped text", () => {
    expect(richTextToPlain("&lt;b&gt;not bold&lt;/b&gt;")).toBe("<b>not bold</b>");
    expect(parseRichText("&lt;b&gt;x&lt;/b&gt;")).toEqual([{ text: "<b>x</b>" }]);
  });

  it("marks headings", () => {
    const spans = parseRichText("## Section title");
    expect(spans).toEqual([{ heading: 2, text: "Section title" }]);
  });

  it("never emits markup as visible text for the real instrument", () => {
    const offenders: string[] = [];
    for (const question of whoVa2022Instrument.questions) {
      for (const field of ["label", "hint", "guidance"] as const) {
        for (const value of Object.values(question[field] ?? {})) {
          if (!value) continue;
          const plain = richTextToPlain(value);
          if (/<\s*\/?\s*(b|strong|i|em|u|br|span)\b/i.test(plain)) {
            offenders.push(`${question.name}.${field}`);
          }
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("covers the guidance fields that actually carry markup", () => {
    const withMarkup = whoVa2022Instrument.questions.filter((question) =>
      /<[a-z/]/i.test(question.guidance?.en ?? "")
    );
    // Guards the premise: if vendoring ever strips this markup, the renderer
    // work below stops being needed and this test says so.
    expect(withMarkup.length).toBeGreaterThan(300);
  });
});
