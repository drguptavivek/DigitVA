/**
 * Renders the spans from `rich-text.ts` as nested text elements.
 *
 * Returns a fragment of spans rather than wrapping them in its own container,
 * so a caller keeps its existing styled element and its own trailing content
 * (the required asterisk on a question label, for example). Nested text is
 * valid on both React Native and react-native-web.
 */
import React, { useMemo } from "react";

import { parseRichText, type RichTextSpan } from "./rich-text.js";

const HEADING_SCALE: Record<number, number> = { 1: 1.5, 2: 1.35, 3: 1.2, 4: 1.1, 5: 1, 6: 1 };

function spanStyle(span: RichTextSpan): Record<string, unknown> | undefined {
  const style: Record<string, unknown> = {};
  if (span.bold) style.fontWeight = "700";
  if (span.italic) style.fontStyle = "italic";
  if (span.underline) style.textDecorationLine = "underline";
  if (span.color) style.color = span.color;
  if (span.backgroundColor) style.backgroundColor = span.backgroundColor;
  if (span.heading) {
    style.fontWeight = "700";
    style.fontSize = 15 * (HEADING_SCALE[span.heading] ?? 1);
  }
  return Object.keys(style).length > 0 ? style : undefined;
}

export function createRichText(Text: React.ElementType) {
  /**
   * `source` is the already-localized, already-interpolated string. Plain text
   * short-circuits to the string itself so the common case adds no elements.
   */
  return function RichText({ source }: { source: string }) {
    const spans = useMemo(() => parseRichText(source), [source]);
    if (spans.length === 1 && spanStyle(spans[0] as RichTextSpan) === undefined) {
      return <>{spans[0]?.text ?? ""}</>;
    }
    return (
      <>
        {spans.map((span, index) => {
          const style = spanStyle(span);
          return style ? (
            <Text key={index} style={style}>
              {span.text}
            </Text>
          ) : (
            <React.Fragment key={index}>{span.text}</React.Fragment>
          );
        })}
      </>
    );
  };
}

export type WhoVaRichText = ReturnType<typeof createRichText>;
