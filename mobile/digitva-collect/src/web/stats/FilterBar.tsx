import { useEffect, useRef, useState } from "react";
import { ScrollView, Text, useWindowDimensions, View, type ViewStyle } from "react-native";

import { DEFAULT_PERIOD, PERIODS, type AreaProject, type Period } from "../../area/api";
import { t, type StringKey } from "../../i18n";
import { fontSize, spacing, useTheme } from "../../theme";
import { Button } from "../../ui";
import { ProjectSelect } from "../../ui/ProjectSelect";
import { AppliedChips, FilterButton, FilterPanel } from "../caseFilters";
import { SelectRow, StatPressable } from "./controls";
import { TABS, type Tab } from "./view";

/** Content width from which the Project control and Filters button share the tab line; narrower, they get their own line above it. */
export const WIDE_BAR = 900;

export const PERIOD_LABELS: Record<Period, StringKey> = {
  "30d": "statsPeriod30d", "90d": "statsPeriod90d", "12m": "statsPeriod12m", all: "statsPeriodAll",
};
const TAB_LABELS: Record<Tab, StringKey> = {
  overview: "statsTabOverview", deaths: "statsTabDeaths", interviews: "statsTabInterviews", codings: "statsTabCodings", projects: "statsTabProjects",
};

/** One filter of the panel: the browser's own select (Area, Source, Overdue). Value "" is not applied. */
export type FilterSelect = { key: string; label: string; options: { value: string; label: string }[]; value: string; onChange: (next: string) => void };

/**
 * The sticky top of Statistics: one line with the tabs, the shared Project control and the Filters button, then the
 * applied filters as removable chips. The Filters panel (the case lists' shared side panel / bottom sheet) holds
 * Period, then the *selects* the screen passes (Area, then the tab's own); the project is not one of its filters, so it
 * is neither counted nor shown as a chip. Every choice applies at once as a URL change made by the screen;
 * *onClearAll* resets the panel's filters in one change, since several single changes would each overwrite the last.
 */
export function FilterBar({ projects, chosen, onProjects, period, onPeriod, selects, tab, onTab, onClearAll }: {
  projects: AreaProject[];
  chosen: string[];
  onProjects: (next: string[]) => void;
  period: Period;
  onPeriod: (next: Period) => void;
  selects: FilterSelect[];
  tab: Tab;
  onTab: (next: Tab) => void;
  onClearAll: () => void;
}) {
  const { ui } = useTheme();
  const [open, setOpen] = useState(false);
  const button = useRef<View>(null);
  const wide = useWindowDimensions().width >= WIDE_BAR;
  const tabs = useRef<ScrollView>(null);
  const tabX = useRef<Partial<Record<Tab, number>>>({});
  // The selected tab scrolls into view when the row does not fit.
  useEffect(() => {
    const x = tabX.current[tab];
    if (x !== undefined) tabs.current?.scrollTo?.({ x: Math.max(0, x - spacing.lg), animated: false });
  }, [tab]);
  const wasOpen = useRef(false);
  // Focus returns to the button once the panel has closed (while it is open the modal holds focus).
  useEffect(() => {
    if (wasOpen.current && !open) (button.current as unknown as { focus?: () => void } | null)?.focus?.();
    wasOpen.current = open;
  }, [open]);

  const chips = [
    ...(period !== DEFAULT_PERIOD ? [{ key: "period", label: `${t("statsPeriod")}: ${t(PERIOD_LABELS[period])}`, clear: () => onPeriod(DEFAULT_PERIOD) }] : []),
    ...selects.filter((select) => select.value).map((select) => ({
      key: select.key,
      label: `${select.label}: ${select.options.find((option) => option.value === select.value)?.label.trim() ?? select.value}`,
      clear: () => select.onChange(""),
    })),
  ];
  return (
    <View style={{ position: "sticky", top: 0, zIndex: 2, backgroundColor: ui.page, paddingVertical: spacing.xs, gap: spacing.xs } as unknown as ViewStyle}>
      <View style={{ flexDirection: wide ? "row" : "column-reverse", alignItems: wide ? "center" : "stretch", gap: spacing.xs, borderBottomWidth: 1, borderBottomColor: ui.border }}>
        <ScrollView
          ref={tabs}
          horizontal
          showsHorizontalScrollIndicator={false}
          accessibilityRole="tablist"
          accessibilityLabel={t("statsTabsLabel")}
          style={{ flexGrow: 0, flexShrink: 1 }}
          contentContainerStyle={{ flexDirection: "row", columnGap: spacing.xxs }}
        >
          {TABS.map((key) => {
            const chosenTab = key === tab;
            return (
              <View
                key={key}
                onLayout={(event) => {
                  tabX.current[key] = event.nativeEvent.layout.x;
                  if (key === tab) tabs.current?.scrollTo?.({ x: Math.max(0, event.nativeEvent.layout.x - spacing.lg), animated: false });
                }}
              >
                <StatPressable
                  role="tab"
                  label={t(TAB_LABELS[key])}
                  selected={chosenTab}
                  onPress={() => onTab(key)}
                  style={{ minHeight: 44, justifyContent: "center", paddingHorizontal: spacing.sm, borderBottomWidth: 3, borderBottomColor: chosenTab ? ui.primary : "transparent" }}
                >
                  <Text style={{ fontSize: fontSize.body, fontWeight: chosenTab ? "600" : "400", color: chosenTab ? ui.foreground : ui.mutedForeground }}>{t(TAB_LABELS[key])}</Text>
                </StatPressable>
              </View>
            );
          })}
        </ScrollView>
        <View style={{ flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: spacing.xs, ...(wide ? { marginLeft: "auto" } : null) } as ViewStyle}>
          <ProjectSelect
            multiple
            projects={projects.map((row) => ({ id: row.project_id, name: row.project_name }))}
            value={chosen}
            onChange={onProjects}
          />
          <FilterButton
            ref={button}
            label={t("statsFilters")}
            a11yLabel={chips.length ? t("statsFiltersActive", { count: chips.length }) : t("statsFilters")}
            count={chips.length}
            expanded={open}
            onPress={() => setOpen(true)}
          />
        </View>
      </View>
      {chips.length ? <AppliedChips chips={chips} onClearAll={onClearAll} /> : null}
      <FilterPanel
        open={open}
        title={t("statsFilters")}
        onClose={() => setOpen(false)}
        footer={(
          <>
            <Button kind="secondary" label={t("clearAll")} onPress={onClearAll} />
            <Button label={t("statsProjectDone")} onPress={() => setOpen(false)} />
          </>
        )}
      >
        <SelectRow
          label={t("statsPeriod")}
          options={PERIODS.map((value) => ({ value, label: t(PERIOD_LABELS[value]) }))}
          value={period}
          onChange={onPeriod}
        />
        {selects.map((select) => <SelectRow key={select.key} label={select.label} options={select.options} value={select.value} onChange={select.onChange} />)}
      </FilterPanel>
    </View>
  );
}
