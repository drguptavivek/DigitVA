/**
 * The inline markup ODK allows in labels, hints, guidance hints, notes and
 * choice labels.
 *
 * Why this exists: 337 of the 449 WHO 2022 questions carry HTML in their
 * guidance (`<span style="color:blue">Record the name ...</span>`), and a few
 * hints do too. The presentation layer used to flatten it with a tag-stripping
 * `plainText`, so no tags leaked but every distinction the form author drew —
 * the blue guidance colour, emphasis, links — was silently discarded. This
 * renders that markup instead of dropping it.
 *
 * Why a parser rather than `dangerouslySetInnerHTML`: the same instrument has
 * to render in React Native, which has no DOM. Producing styled spans works on
 * both, and it cannot inject markup — the output is only ever text plus style
 * flags, so hostile content in a form definition degrades to visible text
 * instead of executing.
 *
 * Supported, matching what ODK clients render:
 *
 *   **bold**  __bold__  *italic*  _italic_
 *   # Heading (through ######)
 *   [label](https://example.org)
 *   <b> <strong> <i> <em> <u> <br>
 *   <span style="color:blue; background-color:#eee">...</span>
 *
 * Anything else is passed through as literal text, which is what ODK does with
 * markup it does not implement.
 */

export interface RichTextSpan {
  text: string;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  color?: string;
  backgroundColor?: string;
  href?: string;
  /** 1-6 for `# Heading`; absent for body text. */
  heading?: number;
}

interface SpanStyle {
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  color?: string;
  backgroundColor?: string;
  href?: string;
  heading?: number;
}

// Longer names first, and the name must end at whitespace, `/` or `>`:
// otherwise the `b` alternative matches the start of `<br>` and swallows it as
// a bold tag whose attributes are "r".
const TAG = /<\s*(\/?)\s*(br|b|strong|em|i|u|span)(?=[\s/>])([^>]*)>/iy;
const STYLE_DECLARATION = /([a-z-]+)\s*:\s*([^;]+)/gi;
const LINK = /\[([^\]]*)\]\(([^)\s]+)\)/y;
const HEADING = /^(#{1,6})\s+/;

const ENTITIES: Record<string, string> = {
  "&nbsp;": "\u00a0",
  "&amp;": "&",
  "&lt;": "<",
  "&gt;": ">",
  "&quot;": '"',
  "&#39;": "'",
  "&apos;": "'"
};

/**
 * Decoded after tag parsing, never before: decoding `&lt;` first would
 * manufacture a tag out of escaped text.
 */
function decodeEntities(text: string): string {
  return text.replace(/&(nbsp|amp|lt|gt|quot|apos|#39);/g, (match) => ENTITIES[match] ?? match);
}

/** CSS colours are passed to the renderer as-is; reject anything exotic. */
function safeColor(value: string): string | undefined {
  const trimmed = value.trim();
  return /^(#[0-9a-f]{3,8}|[a-z]+|rgba?\([\d\s.,%]+\))$/i.test(trimmed) ? trimmed : undefined;
}

function styleFromAttributes(attributes: string): { color?: string; backgroundColor?: string } {
  const style = /style\s*=\s*("([^"]*)"|'([^']*)')/i.exec(attributes);
  const declarations = style?.[2] ?? style?.[3];
  if (!declarations) return {};
  const out: { color?: string; backgroundColor?: string } = {};
  for (const [, property, rawValue] of declarations.matchAll(STYLE_DECLARATION)) {
    const value = safeColor(rawValue ?? "");
    if (!value) continue;
    if (property?.toLowerCase() === "color") out.color = value;
    if (property?.toLowerCase() === "background-color") out.backgroundColor = value;
  }
  return out;
}

function withoutUndefined(style: SpanStyle): SpanStyle {
  const out: SpanStyle = {};
  for (const [key, value] of Object.entries(style)) {
    if (value !== undefined) (out as Record<string, unknown>)[key] = value;
  }
  return out;
}

/**
 * Split `source` into styled spans. Always returns at least one span so a
 * caller can render the result unconditionally.
 */
export function parseRichText(source: string | undefined): RichTextSpan[] {
  const text = source ?? "";
  if (!text) return [{ text: "" }];

  const spans: RichTextSpan[] = [];
  const stack: SpanStyle[] = [];
  let buffer = "";

  const current = (): SpanStyle =>
    stack.reduce<SpanStyle>((merged, style) => ({ ...merged, ...withoutUndefined(style) }), {});

  const flush = () => {
    if (!buffer) return;
    spans.push({ ...current(), text: decodeEntities(buffer) });
    buffer = "";
  };

  let heading: number | undefined;
  const headingMatch = HEADING.exec(text);
  let index = 0;
  if (headingMatch) {
    heading = headingMatch[1]?.length;
    index = headingMatch[0].length;
  }

  while (index < text.length) {
    const rest = text.slice(index);

    // --- HTML tags -------------------------------------------------------
    TAG.lastIndex = index;
    const tag = TAG.exec(text);
    if (tag) {
      const [matched, closing, rawName, attributes] = tag;
      const name = (rawName ?? "").toLowerCase();
      if (name === "br") {
        flush();
        spans.push({ ...current(), text: "\n" });
      } else if (closing) {
        flush();
        stack.pop();
      } else {
        flush();
        if (name === "b" || name === "strong") stack.push({ bold: true });
        else if (name === "i" || name === "em") stack.push({ italic: true });
        else if (name === "u") stack.push({ underline: true });
        else stack.push(styleFromAttributes(attributes ?? ""));
      }
      index += matched.length;
      continue;
    }

    // --- Markdown emphasis ----------------------------------------------
    const emphasis = /^(\*\*|__|\*|_)/.exec(rest);
    if (emphasis) {
      const marker = emphasis[1] as string;
      const bold = marker === "**" || marker === "__";
      const closingIndex = text.indexOf(marker, index + marker.length);
      if (closingIndex > index) {
        flush();
        stack.push(bold ? { bold: true } : { italic: true });
        buffer = text.slice(index + marker.length, closingIndex);
        flush();
        stack.pop();
        index = closingIndex + marker.length;
        continue;
      }
    }

    // --- Markdown links --------------------------------------------------
    LINK.lastIndex = index;
    const link = LINK.exec(text);
    if (link) {
      flush();
      const [matched, label, href] = link;
      spans.push({
        ...current(),
        text: decodeEntities(label ?? ""),
        ...(href ? { href } : {}),
        underline: true
      });
      index += matched.length;
      continue;
    }

    buffer += text[index];
    index += 1;
  }
  flush();

  if (spans.length === 0) spans.push({ text: "" });
  return heading ? spans.map((span) => ({ ...span, heading })) : spans;
}

/** True when `source` carries markup that `parseRichText` would act on. */
export function hasRichText(source: string | undefined): boolean {
  if (!source) return false;
  const spans = parseRichText(source);
  return spans.length > 1 || spans.some((span) => plainLength(span) !== source.length);
}

function plainLength(span: RichTextSpan): number {
  return span.text.length;
}

/** The text with all markup removed, for accessibility labels and tests. */
export function richTextToPlain(source: string | undefined): string {
  return parseRichText(source)
    .map((span) => span.text)
    .join("");
}
