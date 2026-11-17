/**
 * The phone coding workspace's section navigation, like the web's icon rail (WorkspaceLayout.web.tsx): a narrow
 * left rail of one icon button per section that FLOATS over the page (absolute; the page keeps its full width).
 * A rightward swipe on the rail, or the menu button, widens it rightwards to show every section name over a scrim;
 * a leftward swipe, the scrim, the button, choosing a section or Android back collapses it. Buttons do everything the
 * swipe does. Labels carry the full name, response count and attachment count, as on the web. Colours are theme tokens.
 * Native only: its one importer, WorkspaceLayout.tsx, is shadowed on the web by WorkspaceLayout.web.tsx, so
 * gesture-handler and reanimated stay out of the web bundle.
 */
import { useEffect, useState } from "react";
import { BackHandler, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";
import { Gesture, GestureDetector } from "react-native-gesture-handler";
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from "react-native-reanimated";

import { Icon, icons, sectionIcon } from "../Icon";
import { useTheme } from "../theme";
import { useUiStyles } from "../ui";
import type { WorkspaceCategoryNav } from "./contracts";

export const RAIL_WIDTH = 56;
const MAX_EXPANDED = 320;
const SWIPE_DISTANCE = 40;
const ANIMATION_MS = 180;

function sectionLabel(item: WorkspaceCategoryNav) {
  const counts = item.count && item.count > 0 ? `, ${item.count} responses` : "";
  const files = item.attachment_count && item.attachment_count > 0 ? `, ${item.attachment_count} attachments` : "";
  return `${item.nav_label}${counts}${files}`;
}

export function PhoneSectionRail({ categories, selectedCode, onSelect }: {
  categories: WorkspaceCategoryNav[];
  selectedCode: string;
  onSelect: (code: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const { ui } = useTheme();
  const styles = useUiStyles();
  const { width: screenWidth } = useWindowDimensions();
  const expandedWidth = Math.min(MAX_EXPANDED, screenWidth * 0.75);
  const width = useSharedValue(RAIL_WIDTH);
  useEffect(() => { width.value = withTiming(open ? expandedWidth : RAIL_WIDTH, { duration: ANIMATION_MS }); }, [open, expandedWidth, width]);
  // The back button closes the open panel first (it is not a screen).
  useEffect(() => {
    if (!open) return undefined;
    const sub = BackHandler.addEventListener("hardwareBackPress", () => { setOpen(false); return true; });
    return () => sub.remove();
  }, [open]);
  const panelStyle = useAnimatedStyle(() => ({ width: width.value }));
  // Horizontal intent only: a vertical drag fails the pan so the rail and the page still scroll.
  const swipe = Gesture.Pan()
    .runOnJS(true)
    .activeOffsetX([-12, 12])
    .failOffsetY([-12, 12])
    .onEnd((event) => {
      if (event.translationX > SWIPE_DISTANCE) setOpen(true);
      else if (event.translationX < -SWIPE_DISTANCE) setOpen(false);
    });
  const choose = (code: string) => { setOpen(false); onSelect(code); };
  return (
    <View pointerEvents="box-none" style={StyleSheet.absoluteFill}>
      {open ? (
        <Pressable accessibilityElementsHidden importantForAccessibility="no" testID="section-rail-scrim" onPress={() => setOpen(false)} style={[StyleSheet.absoluteFill, { backgroundColor: ui.scrim }]} />
      ) : null}
      <GestureDetector gesture={swipe}>
        <Animated.View
          accessibilityLabel="Case categories"
          accessibilityViewIsModal={open}
          // Semi-opaque while collapsed so the page text beneath stays legible; solid when it is the open panel.
          style={[{ position: "absolute", left: 0, top: 0, bottom: 0, backgroundColor: ui.card, borderRightWidth: 1, borderRightColor: ui.border, opacity: open ? 1 : 0.9, overflow: "hidden", shadowColor: ui.foreground, shadowOpacity: 0.2, shadowRadius: 6, shadowOffset: { width: 2, height: 0 }, elevation: 6 }, panelStyle]}
        >
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={open ? "Hide section names" : "Show section names"}
            accessibilityState={{ expanded: open }}
            onPress={() => setOpen(!open)}
            style={{ minHeight: 48, minWidth: 48, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16 }}
          >
            <Icon name={open ? icons.dismiss : icons.menu} color={ui.primary} size={24} />
            {open ? <Text accessibilityRole="header" style={styles.headline}>Sections</Text> : null}
          </Pressable>
          <ScrollView showsVerticalScrollIndicator={false}>
            {categories.map((item) => {
              const selected = item.code === selectedCode;
              const fg = selected ? ui.primaryForeground : ui.primary;
              const muted = selected ? ui.primaryForeground : ui.mutedForeground;
              return (
                <Pressable
                  key={item.code}
                  accessibilityRole="button"
                  accessibilityLabel={sectionLabel(item)}
                  accessibilityState={{ selected }}
                  onPress={() => choose(item.code)}
                  style={{ minHeight: 48, minWidth: 48, flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 8, backgroundColor: selected ? ui.primary : "transparent" }}
                >
                  <Icon name={sectionIcon(item.icon_name)} color={fg} size={24} />
                  {open ? (
                    <>
                      <Text style={[styles.text, { flex: 1, color: selected ? ui.primaryForeground : ui.foreground }]}>{item.nav_label}</Text>
                      {item.count && item.count > 0 ? <Text style={[styles.text, { color: muted }]}>{item.count}</Text> : null}
                      {item.attachment_count && item.attachment_count > 0 ? (
                        <View style={{ flexDirection: "row", alignItems: "center", gap: 2 }}>
                          <Icon name={icons.attachments} color={muted} size={16} />
                          <Text style={[styles.text, { color: muted }]}>{item.attachment_count}</Text>
                        </View>
                      ) : null}
                    </>
                  ) : null}
                </Pressable>
              );
            })}
          </ScrollView>
        </Animated.View>
      </GestureDetector>
    </View>
  );
}
