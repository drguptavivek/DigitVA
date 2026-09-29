/**
 * Section navigation for the shared form, drawn as a stepper.
 *
 * - Wide form: a vertical stepper beside the questions, one circle per
 *   visible section joined by a line, every section named and tappable.
 *   Nested sections are indented under their parent, and a parent that is
 *   not itself a page (it holds no questions) is shown as a plain heading.
 * - Medium and narrow forms: a horizontal stepper across the top with only
 *   the current section named beneath it. When the circles would crowd, it
 *   collapses to "done - current - remaining" instead of shrinking. Tapping
 *   it opens a flyout drawer holding the vertical stepper.
 *
 * The visible list changes as answers gate sections in and out (three
 * sections before consent, fifteen to twenty after), so items are keyed by
 * section name, the total is always the current visible count, a note says
 * that more sections may appear while most of the form is still gated, and
 * a section that has just appeared fades in (instantly under reduced motion).
 *
 * Status is shape plus colour, never colour alone: an empty ring for not
 * started, a half-filled ring for in progress, a ring with a tick for
 * complete, a red ring with "!" for a section with validation issues, and a
 * filled circle with a white dot for the current section.
 */
import React, { useEffect, useRef, useState } from "react";

import type { WhoVaUiMessages } from "../i18n.js";
import { withWebTheme } from "./web-theme.js";

export type SectionNavStatus = "empty" | "started" | "complete" | "issues";

export interface SectionNavItem {
  name: string;
  /** "3. Open narrative", already localized. */
  label: string;
  status: SectionNavStatus;
  active: boolean;
  /** Nesting depth among the visible sections, 0 for a top-level one. */
  depth: number;
  /** A heading to show above this item: the label of a parent that is not a page. */
  groupLabel?: string;
}

interface SectionNavPrimitives {
  View: React.ElementType;
  Text: React.ElementType;
  Pressable: React.ElementType;
  ScrollView: React.ElementType;
  /**
   * Hosts the drawer above the page. react-native-web's Modal portals its
   * children to document.body, which is the only way out of the form's own
   * stacking context: every react-native-web View is `position: relative;
   * z-index: 0`, so a z-index inside the form can never rise above a host
   * element such as a fixed navbar. Without it the drawer renders inline.
   */
  Modal?: React.ElementType | undefined;
}

const STATUS_SUFFIX: Record<SectionNavStatus, string> = {
  empty: "",
  started: ", started",
  complete: ", completed",
  issues: ", has issues"
};

/**
 * Circle diameter, the gap either side of a connecting line and the shortest
 * line that still reads as one: a circle needs DIAMETER + 2 * GAP + MIN_LINE
 * of row width after the first. The strip has no padding, so the measured
 * row width is the available width.
 */
const STEP_DIAMETER = 20;
const STEP_GAP = 6;
const STEP_MIN_LINE = 12;

/** True when `count` circles joined by lines fit in `width` without shrinking. */
export function stepperFits(width: number, count: number): boolean {
  if (count <= 1) return true;
  return STEP_DIAMETER + (count - 1) * (STEP_DIAMETER + 2 * STEP_GAP + STEP_MIN_LINE) <= width;
}
const MAX_INDENT = 2;
const INDENT = 16;

/** Focusable descendants of a drawer panel, in document order (web only). */
function focusableWithin(node: unknown): HTMLElement[] {
  if (typeof HTMLElement === "undefined" || !(node instanceof HTMLElement)) return [];
  return Array.from(
    node.querySelectorAll<HTMLElement>('button, [href], input, [tabindex]:not([tabindex="-1"])')
  );
}

/** Scroll `box` just enough to show `item`, touching nothing outside the box. */
function keepInView(box: unknown, item: unknown): void {
  if (typeof HTMLElement === "undefined" || !(box instanceof HTMLElement) || !(item instanceof HTMLElement))
    return;
  const top = item.offsetTop - box.offsetTop;
  const bottom = top + item.offsetHeight;
  if (top < box.scrollTop) box.scrollTo({ top: top - 8 });
  else if (bottom > box.scrollTop + box.clientHeight) box.scrollTo({ top: bottom - box.clientHeight + 8 });
}

function sectionTitle(item: SectionNavItem): string {
  return item.label.replace(/^\d+\.\s*/, "");
}

/**
 * Names of the items that were not in the list a render ago. They start
 * transparent and settle on the next frame, which the transition turns into
 * a short fade.
 */
function useJustAdded(items: readonly SectionNavItem[]): ReadonlySet<string> {
  const names = items.map((item) => item.name);
  const [settled, setSettled] = useState<ReadonlySet<string>>(() => new Set(names));
  const pending = names.filter((name) => !settled.has(name));
  const pendingKey = pending.join("\u0000");
  useEffect(() => {
    if (!pendingKey) return;
    const settle = () => setSettled(new Set(names));
    if (typeof requestAnimationFrame === "function") {
      const frame = requestAnimationFrame(settle);
      return () => cancelAnimationFrame(frame);
    }
    settle();
    return undefined;
    // `names` is derived from `items`; the key captures the change that matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingKey]);
  return new Set(pending);
}

export function createSectionNavigation({ View, Text, Pressable, ScrollView, Modal }: SectionNavPrimitives) {
  /**
   * One stepper circle. The status node (`section-status-<name>`) exists only
   * once a section has been touched, so an untouched section has none.
   */
  function StepCircle({ item, small }: { item: SectionNavItem; small?: boolean }) {
    const { status, active, name } = item;
    const statusProps = status === "empty" ? {} : { testID: `section-status-${name}` };
    const glyph = status === "complete" ? "✓" : status === "issues" ? "!" : "";
    return (
      <View
        aria-hidden="true"
        style={[
          navStyles.circle,
          small && navStyles.circleSmall,
          status === "complete" && navStyles.circleComplete,
          status === "issues" && navStyles.circleIssues,
          active && navStyles.circleActive
        ]}
        {...statusProps}
      >
        {glyph ? (
          <Text
            style={[
              navStyles.circleGlyph,
              small && navStyles.circleGlyphSmall,
              status === "issues" && navStyles.circleGlyphIssues,
              active && navStyles.circleGlyphActive
            ]}
          >
            {glyph}
          </Text>
        ) : active ? (
          <View style={navStyles.circleDot} />
        ) : status === "started" ? (
          <View style={navStyles.circleHalf} />
        ) : null}
      </View>
    );
  }

  /** The vertical stepper: every visible section, named, tappable. Used by the rail and the drawer. */
  function VerticalStepper({
    items,
    onSelect,
    scrollBox
  }: {
    items: readonly SectionNavItem[];
    onSelect: (name: string) => void;
    /** The rail's own scroll box, kept scrolled to the current item without moving the page. */
    scrollBox?: React.MutableRefObject<unknown> | undefined;
  }) {
    const activeRef = useRef<unknown>(null);
    const activeName = items.find((item) => item.active)?.name;
    useEffect(() => {
      keepInView(scrollBox?.current, activeRef.current);
    }, [activeName, scrollBox]);
    const activeIndex = Math.max(
      0,
      items.findIndex((item) => item.active)
    );
    const justAdded = useJustAdded(items);
    return (
      <>
        {items.map((item, index) => (
          <React.Fragment key={item.name}>
            {item.groupLabel ? (
              <Text style={[navStyles.groupLabel, { marginLeft: Math.min(item.depth, MAX_INDENT) * INDENT }]}>
                {item.groupLabel}
              </Text>
            ) : null}
            <Pressable
              accessibilityLabel={`${item.label}${STATUS_SUFFIX[item.status]}`}
              accessibilityRole="button"
              accessibilityState={{ selected: item.active }}
              aria-invalid={item.status === "issues" || undefined}
              testID="section-slider-item"
              {...(item.active ? { ref: activeRef } : {})}
              onPress={() => onSelect(item.name)}
              style={[
                navStyles.step,
                navStyles.stepEntry,
                { marginLeft: Math.min(item.depth, MAX_INDENT) * INDENT },
                justAdded.has(item.name) && navStyles.stepEntering
              ]}
            >
              <View style={navStyles.stepRail}>
                <StepCircle item={item} />
                {index < items.length - 1 ? (
                  <View
                    aria-hidden="true"
                    style={[navStyles.stepLine, index < activeIndex && navStyles.stepLineDone]}
                  />
                ) : null}
              </View>
              <Text
                style={[
                  navStyles.stepText,
                  (item.active || item.status === "complete") && navStyles.stepTextStrong,
                  item.status === "issues" && navStyles.stepTextIssues
                ]}
              >
                {item.label}
              </Text>
            </Pressable>
          </React.Fragment>
        ))}
      </>
    );
  }

  /** The persistent stepper beside the questions on a wide form. */
  function SectionRail({
    items,
    messages,
    moreToCome,
    onSelect
  }: {
    items: readonly SectionNavItem[];
    messages: WhoVaUiMessages;
    moreToCome: boolean;
    onSelect: (name: string) => void;
  }) {
    const railRef = useRef<unknown>(null);
    return (
      <View
        ref={railRef}
        role="navigation"
        aria-label={messages.sections}
        style={navStyles.rail}
        testID="section-rail"
      >
        <VerticalStepper items={items} onSelect={onSelect} scrollBox={railRef} />
        {moreToCome ? <Text style={navStyles.moreNote}>{messages.moreSectionsNote}</Text> : null}
      </View>
    );
  }

  /**
   * The horizontal stepper on a medium or narrow form. The whole strip is the
   * drawer's toggle: it shows progress and names the current section, and
   * tapping it opens the full list. Collapses to done - current - remaining
   * rather than shrinking when the sections outnumber the circles that fit.
   */
  function SectionHeaderBar({
    current,
    items,
    messages,
    moreToCome,
    onOpen,
    open,
    toggleRef,
    total
  }: {
    current: number;
    items: readonly SectionNavItem[];
    messages: WhoVaUiMessages;
    moreToCome: boolean;
    onOpen: () => void;
    open: boolean;
    toggleRef: React.MutableRefObject<unknown>;
    total: number;
  }) {
    const [width, setWidth] = useState(0);
    const activeIndex = Math.max(
      0,
      items.findIndex((item) => item.active)
    );
    const active = items[activeIndex];
    // Until the first layout, only a short list is drawn in full: a long one
    // must never flash its overflow.
    const collapsed = width > 0 ? !stepperFits(width, items.length) : items.length > 8;
    const done = items.filter((item) => item.status === "complete").length;
    const position = messages.sectionProgress(current, total);
    const title = active ? sectionTitle(active) : "";
    // Where the current circle sits, so its name can start beneath it.
    const pitch = items.length > 1 ? (width - STEP_DIAMETER) / (items.length - 1) : 0;
    const labelOffset = collapsed ? 0 : Math.max(0, Math.min(Math.round(activeIndex * pitch), width - 220));

    return (
      <Pressable
        ref={toggleRef}
        accessibilityLabel={`${messages.sections}: ${position}${title ? ` · ${title}` : ""}`}
        accessibilityRole="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onPress={onOpen}
        style={navStyles.header}
        testID="section-drawer-toggle"
      >
        <View
          aria-hidden="true"
          style={navStyles.strip}
          testID="section-progress"
          onLayout={(event: { nativeEvent: { layout: { width: number } } }) =>
            setWidth(event.nativeEvent.layout.width)
          }
        >
          {collapsed && active ? (
            <>
              <Text style={navStyles.stripCount}>{messages.sectionsDone(done)}</Text>
              <View
                style={[navStyles.stripLine, navStyles.stripLineDone, { flexGrow: Math.max(1, activeIndex) }]}
              />
              <StepCircle item={active} small />
              <View style={[navStyles.stripLine, { flexGrow: Math.max(1, total - current) }]} />
              <Text style={navStyles.stripCount}>{messages.sectionsRemaining(total - current)}</Text>
            </>
          ) : (
            items.map((item, index) => (
              <React.Fragment key={item.name}>
                <StepCircle item={item} small />
                {index < items.length - 1 ? (
                  <View style={[navStyles.stripLine, index < activeIndex && navStyles.stripLineDone]} />
                ) : null}
              </React.Fragment>
            ))
          )}
        </View>
        <View style={navStyles.headerRow}>
          <View style={[navStyles.headerLead, { marginLeft: labelOffset }]}>
            <Text numberOfLines={1} style={navStyles.headerText}>
              {position}
            </Text>
            {moreToCome ? <Text style={navStyles.moreNoteInline}>{messages.moreSectionsNote}</Text> : null}
          </View>
          <Text style={navStyles.headerHint}>{`☰ ${messages.sections}`}</Text>
        </View>
      </Pressable>
    );
  }

  /**
   * The flyout list on a medium or narrow form. Modal: Escape and the scrim
   * close it, Tab cycles inside it, and focus returns to the strip that
   * opened it. It appears and disappears in place, so there is no motion to
   * reduce.
   */
  function SectionDrawer({
    items,
    messages,
    moreToCome,
    onClose,
    onSelect,
    open,
    toggleRef
  }: {
    items: readonly SectionNavItem[];
    messages: WhoVaUiMessages;
    moreToCome: boolean;
    onClose: () => void;
    onSelect: (name: string) => void;
    open: boolean;
    toggleRef: React.MutableRefObject<unknown>;
  }) {
    const panelRef = useRef<unknown>(null);
    const closeRef = useRef<unknown>(null);

    useEffect(() => {
      if (!open) return;
      const focus = (node: unknown) => (node as { focus?: () => void } | null)?.focus?.();
      focus(closeRef.current);
      const opener = toggleRef.current;
      return () => focus(opener);
    }, [open, toggleRef]);

    if (!open) return null;

    const onKeyDown = (event: {
      key?: string;
      shiftKey?: boolean;
      preventDefault?: () => void;
      nativeEvent?: { key?: string; shiftKey?: boolean };
    }) => {
      const key = event.key ?? event.nativeEvent?.key;
      if (key === "Escape") {
        onClose();
        return;
      }
      if (key !== "Tab") return;
      const focusables = focusableWithin(panelRef.current);
      if (!focusables.length || typeof document === "undefined") return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const shift = event.shiftKey ?? event.nativeEvent?.shiftKey ?? false;
      if (shift && document.activeElement === first) {
        event.preventDefault?.();
        last?.focus();
      } else if (!shift && document.activeElement === last) {
        event.preventDefault?.();
        first?.focus();
      }
    };

    const overlay = (
      <View style={navStyles.overlay} testID="section-drawer-overlay">
        <Pressable
          accessibilityLabel={messages.close}
          accessibilityRole="button"
          onPress={onClose}
          style={navStyles.scrim}
          testID="section-drawer-scrim"
        />
        <View
          ref={panelRef}
          accessibilityViewIsModal
          aria-label={messages.sections}
          aria-modal="true"
          onKeyDown={onKeyDown}
          role="dialog"
          style={navStyles.panel}
          testID="section-drawer"
        >
          <View style={navStyles.panelHeader}>
            <Text style={navStyles.panelTitle}>{messages.sections}</Text>
            <Pressable
              ref={closeRef}
              accessibilityLabel={messages.close}
              accessibilityRole="button"
              onPress={onClose}
              style={navStyles.closeButton}
              testID="section-drawer-close"
            >
              <Text aria-hidden="true" style={navStyles.closeGlyph}>
                ✕
              </Text>
            </Pressable>
          </View>
          <ScrollView keyboardShouldPersistTaps="handled" style={navStyles.panelList}>
            <VerticalStepper
              items={items}
              onSelect={(name) => {
                onSelect(name);
                onClose();
              }}
            />
            {moreToCome ? <Text style={navStyles.moreNote}>{messages.moreSectionsNote}</Text> : null}
          </ScrollView>
        </View>
      </View>
    );
    if (!Modal) return overlay;
    return (
      <Modal animationType="none" onRequestClose={onClose} transparent visible>
        {overlay}
      </Modal>
    );
  }

  // Memoised: their props only change when a section's status, the current
  // section or the visible list changes, not on every answer.
  return {
    SectionRail: React.memo(SectionRail),
    SectionHeaderBar: React.memo(SectionHeaderBar),
    SectionDrawer: React.memo(SectionDrawer)
  };
}

export const navStyles = {
  // Circles
  circle: withWebTheme(
    {
      alignItems: "center" as const,
      backgroundColor: "#ffffff",
      borderColor: "#b8c2d1",
      borderRadius: 999,
      borderWidth: 2,
      flexShrink: 0,
      height: 22,
      justifyContent: "center" as const,
      overflow: "hidden" as const,
      width: 22
    },
    { backgroundColor: "surface", borderColor: "controlBorder" }
  ),
  circleSmall: { height: STEP_DIAMETER, width: STEP_DIAMETER },
  circleComplete: withWebTheme({ borderColor: "#147d64" }, { borderColor: "brand" }),
  circleIssues: withWebTheme({ borderColor: "#b34231" }, { borderColor: "danger" }),
  circleActive: withWebTheme(
    { backgroundColor: "#147d64", borderColor: "#147d64" },
    { backgroundColor: "brand", borderColor: "brand" }
  ),
  circleGlyph: withWebTheme(
    { color: "#147d64", fontSize: 13, fontWeight: "700" as const, lineHeight: 16 },
    { color: "brand" }
  ),
  circleGlyphSmall: { fontSize: 12, lineHeight: 14 },
  circleGlyphIssues: withWebTheme({ color: "#b34231" }, { color: "danger" }),
  circleGlyphActive: { color: "#ffffff" },
  circleDot: { backgroundColor: "#ffffff", borderRadius: 999, height: 8, width: 8 },
  circleHalf: withWebTheme(
    {
      backgroundColor: "#147d64",
      height: "100%",
      left: 0,
      position: "absolute" as const,
      top: 0,
      width: "50%"
    },
    { backgroundColor: "brand" }
  ),
  // Vertical stepper (rail and drawer)
  rail: withWebTheme(
    { alignSelf: "flex-start" as const, paddingTop: 4, position: "relative" as const, width: 236 },
    { position: "stickyRail" }
  ),
  groupLabel: withWebTheme(
    {
      color: "#536b64",
      fontSize: 12,
      fontWeight: "700" as const,
      letterSpacing: 0.4,
      lineHeight: 16,
      marginBottom: 6,
      marginTop: 2,
      textTransform: "uppercase" as const
    },
    { color: "muted" }
  ),
  step: { columnGap: 12, flexDirection: "row" as const, minHeight: 40 },
  stepEntry: withWebTheme({ opacity: 1 }, { opacity: "entryTransition" }),
  stepEntering: { opacity: 0 },
  stepRail: { alignItems: "center" as const, width: 22 },
  stepLine: withWebTheme(
    { backgroundColor: "#dce6e1", flex: 1, minHeight: 14, width: 2 },
    { backgroundColor: "border" }
  ),
  stepLineDone: withWebTheme({ backgroundColor: "#147d64" }, { backgroundColor: "brand" }),
  stepText: withWebTheme(
    { color: "#536b64", flexShrink: 1, fontSize: 14, lineHeight: 22, paddingBottom: 14 },
    { color: "muted" }
  ),
  stepTextStrong: withWebTheme({ color: "#183d33" }, { color: "ink" }),
  stepTextIssues: withWebTheme({ color: "#8c3022" }, { color: "dangerStrong" }),
  moreNote: withWebTheme(
    {
      color: "#536b64",
      fontSize: 13,
      fontStyle: "italic" as const,
      lineHeight: 18,
      marginTop: 4,
      paddingLeft: 34
    },
    { color: "muted" }
  ),
  moreNoteInline: withWebTheme(
    { color: "#536b64", fontSize: 12, fontStyle: "italic" as const, lineHeight: 16 },
    { color: "muted" }
  ),
  // Horizontal stepper (header)
  header: { marginBottom: 16, rowGap: 8 },
  strip: {
    alignItems: "center" as const,
    columnGap: STEP_GAP,
    flexDirection: "row" as const,
    overflow: "hidden" as const,
    width: "100%"
  },
  stripLine: withWebTheme(
    { backgroundColor: "#dce6e1", flexBasis: 0, flexGrow: 1, height: 2, minWidth: 12 },
    { backgroundColor: "border" }
  ),
  stripLineDone: withWebTheme({ backgroundColor: "#147d64" }, { backgroundColor: "brand" }),
  stripCount: withWebTheme(
    { color: "#536b64", fontSize: 12, fontWeight: "600" as const, lineHeight: 16 },
    { color: "muted" }
  ),
  headerRow: {
    alignItems: "flex-start" as const,
    columnGap: 12,
    flexDirection: "row" as const,
    justifyContent: "space-between" as const
  },
  headerLead: { flexShrink: 1, rowGap: 2 },
  headerText: withWebTheme(
    { color: "#183d33", fontSize: 14, fontWeight: "700" as const, lineHeight: 20 },
    { color: "ink" }
  ),
  headerHint: withWebTheme(
    { color: "#536b64", flexShrink: 0, fontSize: 13, fontWeight: "600" as const, lineHeight: 20 },
    { color: "muted" }
  ),
  // Drawer
  overlay: withWebTheme(
    { bottom: 0, left: 0, position: "absolute" as const, right: 0, top: 0, zIndex: 1000 },
    { position: "overlayPosition" }
  ),
  scrim: {
    backgroundColor: "rgba(15, 23, 42, 0.45)",
    bottom: 0,
    left: 0,
    position: "absolute" as const,
    right: 0,
    top: 0
  },
  panel: withWebTheme(
    {
      backgroundColor: "#ffffff",
      bottom: 0,
      // Opens on the same side as the "Sections" toggle (top right).
      right: 0,
      maxWidth: "85%",
      paddingHorizontal: 16,
      paddingVertical: 10,
      position: "absolute" as const,
      top: 0,
      width: 320
    },
    { backgroundColor: "surface" }
  ),
  panelHeader: {
    alignItems: "center" as const,
    flexDirection: "row" as const,
    justifyContent: "space-between" as const,
    marginBottom: 8
  },
  panelTitle: withWebTheme(
    { color: "#12372d", fontSize: 16, fontWeight: "700" as const, lineHeight: 24 },
    { color: "brandDeep" }
  ),
  panelList: { flex: 1 },
  closeButton: {
    alignItems: "center" as const,
    borderRadius: 999,
    height: 44,
    justifyContent: "center" as const,
    width: 44
  },
  closeGlyph: withWebTheme({ color: "#12372d", fontSize: 18, lineHeight: 22 }, { color: "brandDeep" })
};
