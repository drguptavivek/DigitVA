import React, { useEffect, useRef, useState } from "react";
import { Image, Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";

import { radius } from "../theme";
import type { WorkspaceLayoutProps } from "./WorkspaceLayout";

const BLUE = "#004687";
const PAGE = "#f7f7f7";
const CARD = "#ffffff";
const MUTED = "#f3f5f8";
const TEXT = "#333333";
const BORDER = "#e1e5ea";
const ROBOTO = "Roboto, Arial, sans-serif";
const WIDE_BREAKPOINT = 900;

function FaIcon({ name, label, color }: { name: string; label?: string; color?: string }) {
  return React.createElement("i", {
    className: `fas ${name}`,
    style: color ? { color } : undefined,
    "aria-hidden": label ? undefined : true,
    "aria-label": label,
  });
}

function WebButton({ label, onPress, disabled = false }: { label: string; onPress: () => void; disabled?: boolean }) {
  return React.createElement("button", {
    type: "button",
    disabled,
    onClick: onPress,
    style: {
      background: disabled ? "#f8f9fa" : CARD,
      border: `1px solid ${disabled ? "#c7cdd3" : BLUE}`,
      borderRadius: 4,
      color: disabled ? "#7b8792" : BLUE,
      cursor: disabled ? "default" : "pointer",
      fontFamily: ROBOTO,
      fontSize: 13,
      fontWeight: 600,
      minHeight: 36,
      padding: "6px 12px",
    },
  }, label);
}

function WebLink({ href, children }: { href: string; children: React.ReactNode }) {
  return React.createElement("a", {
    href,
    style: { color: "#fff", fontFamily: ROBOTO, fontSize: 12, fontWeight: 700, textDecoration: "none" },
  }, children);
}

function DetailsItem({ icon, label, value, demo, flex }: { icon: string; label: string; value: string; demo?: boolean; flex: number }) {
  return <View style={[webStyles.detailItem, { flex }]}>
    <View style={webStyles.detailLabel}><FaIcon name={icon} color={BLUE} /><Text style={webStyles.detailLabelText}>{label}</Text>{demo ? <Text style={webStyles.demo}>DEMO</Text> : null}</View>
    <Text style={webStyles.detailValue}>{value || "-"}</Text>
  </View>;
}

function hintText(mode: WorkspaceLayoutProps["identity"]["mode"]): string[] {
  if (mode === "view") return [
    "This submission is open in read-only mode; nothing on this page changes it.",
    "Use the category list to move between sections of the interview.",
  ];
  if (mode === "reviewing") return [
    'Utilize the "Notes" panel on the right edge for maintaining observations.',
    "Submit the Reviewer COD to complete this QA. Saved NQA and Social Autopsy entries are intermediate work only.",
  ];
  return [
    'Utilize the "Notes" panel on the right edge for maintaining observations.',
    'Please mention the "VA Form ID" or "SID" while reporting technical issues to the Central Admin Team (AIIMS, New Delhi), if any.',
  ];
}

function CategoryNavigation({
  categories,
  formId,
  smartvaAvailable,
  selectedCode,
  onSelectCategory,
  open,
  narrow,
  setOpen,
}: Pick<WorkspaceLayoutProps, "categories" | "selectedCode" | "onSelectCategory"> & { formId: string; smartvaAvailable: boolean; open: boolean; narrow: boolean; setOpen: (open: boolean) => void }) {
  return <View style={[webStyles.categoryColumn, narrow && webStyles.categoryColumnNarrow, !open && webStyles.categoryColumnClosed]}>
    <View style={webStyles.categoryCard}>
      <View style={webStyles.categoryHeader}><FaIcon name="fa-file-medical-alt" color="#fff" /><Text style={webStyles.categoryHeaderText}>{formId || "Categories"}</Text></View>
      <View style={webStyles.categoryList}>
        {categories.length ? categories.map((item) => {
          const selected = selectedCode === item.code;
          const attachmentCount = typeof (item as { attachment_count?: unknown }).attachment_count === "number"
            ? (item as { attachment_count: number }).attachment_count
            : 0;
          return <Pressable
            key={item.code}
            accessibilityRole="button"
            accessibilityState={{ selected }}
            onPress={() => { onSelectCategory(item.code); setOpen(false); }}
            style={({ pressed }) => [webStyles.categoryItem, selected && webStyles.categoryItemSelected, pressed && webStyles.pressed]}
          >
            <FaIcon name={item.icon_name ?? "fa-folder-open"} color={selected ? "#fff" : BLUE} />
            <Text style={[webStyles.categoryLabel, selected && webStyles.categoryLabelSelected]}>{item.nav_label}</Text>
            {item.count && item.count > 0 ? <Text style={webStyles.categoryBadge}>{item.count}</Text> : null}
            {attachmentCount > 0 ? <View style={webStyles.attachmentBadge} accessibilityLabel={`${attachmentCount} attachments`}><FaIcon name="fa-paperclip" color="#687482" /><Text style={webStyles.attachmentBadgeText}>{attachmentCount}</Text></View> : null}
          </Pressable>;
        }) : <Text style={webStyles.empty}>No visible categories for this submission.</Text>}
      </View>
    </View>
    <View style={webStyles.smartvaCard}>
      <Text style={webStyles.smartvaTitle}><FaIcon name="fa-chart-pie" color={BLUE} /> SmartVA</Text>
      <Text style={webStyles.smartvaText}>{smartvaAvailable ? "Done (result shown in the assessment steps)" : "Results are shown in COD Assessment when available."}</Text>
    </View>
  </View>;
}

export function WorkspaceLayout({
  identity,
  workspace,
  categories,
  selectedCode,
  categoryLoading,
  onSelectCategory,
  onExit,
  children,
  notes,
}: WorkspaceLayoutProps) {
  const { width } = useWindowDimensions();
  const wide = width >= WIDE_BREAKPOINT;
  const [categoriesOpen, setCategoriesOpen] = useState(wide);
  const [notesOpen, setNotesOpen] = useState(false);
  const wasWide = useRef(wide);

  useEffect(() => {
    if (wide) setCategoriesOpen(true);
    else if (wasWide.current) setCategoriesOpen(false);
    wasWide.current = wide;
  }, [wide]);

  useEffect(() => {
    if (!notesOpen || typeof document === "undefined") return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNotesOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    document.getElementById("digitva-notes-close")?.focus();
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [notesOpen]);

  const notesWasOpen = useRef(false);
  useEffect(() => {
    if (typeof document !== "undefined" && notesWasOpen.current && !notesOpen) document.getElementById("digitva-notes-trigger")?.focus();
    notesWasOpen.current = notesOpen;
  }, [notesOpen]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    const links = [
      ["/static/vendors/roboto/roboto.css", "digitva-workspace-roboto"],
      ["/static/vendors/fontawesome/css/all.min.css", "digitva-workspace-fontawesome"],
    ] as const;
    for (const [href, id] of links) {
      if (document.getElementById(id)) continue;
      const link = document.createElement("link");
      link.id = id;
      link.rel = "stylesheet";
      link.href = href;
      document.head.appendChild(link);
    }
  }, []);

  const selectedIndex = Math.max(0, categories.findIndex((item) => item.code === selectedCode));
  const previous = categories[selectedIndex - 1];
  const next = categories[selectedIndex + 1];
  const age = workspace.case.age === null || workspace.case.age === undefined ? "-" : String(workspace.case.age);
  const gender = workspace.case.gender ?? "-";
  const projectSite = `${workspace.case.project_code ?? "-"}/${workspace.case.site_code ?? "-"}`;
  const projectLabel = workspace.case.is_demo_project ? `${projectSite} - TESTING PROJECT` : projectSite;
  const hints = hintText(identity.mode);
  const modeLink = identity.mode === "reviewing" ? "/reviewing" : "/coding";
  const modeIcon = identity.mode === "reviewing" ? "fa-user-check" : "fa-file-medical";
  const modeLabel = identity.mode === "reviewing" ? "VA Review" : "VA Coding";

  return <View style={webStyles.safe}>
    <View style={webStyles.appHeader}>
      <View style={webStyles.headerInner}>
        <WebLink href="/vaindex"><Image source={{ uri: "/static/digitva_logo.png" }} accessibilityLabel="DigitVA" resizeMode="contain" style={webStyles.logo} /></WebLink>
        <View style={webStyles.headerLinks}>
          <WebLink href={modeLink}><FaIcon name={modeIcon} color="#fff" /> {modeLabel}</WebLink>
          <WebLink href="/help"><FaIcon name="fa-question-circle" color="#fff" /> Help</WebLink>
        </View>
      </View>
    </View>
    <ScrollView contentContainerStyle={webStyles.page}>
      <View style={webStyles.content}>
        <View style={webStyles.hintsCard}>
          <View style={webStyles.cardHeadingRow}>
            <Text style={webStyles.hintsHeading}><FaIcon name="fa-info-circle" color={BLUE} /> Hints</Text>
            <WebButton label="Back to Dashboard" onPress={onExit} />
          </View>
          <Text style={webStyles.hintLead}>{identity.mode === "reviewing" ? "Verbal Autopsy Quality Assurance" : identity.mode === "view" ? "Verbal Autopsy Submission (read-only)" : "Verbal Autopsy Cause of Death Ascertainment"}</Text>
          <View style={webStyles.hintList}>
            {hints.map((hint) => <Text key={hint} style={webStyles.hint}><Text style={webStyles.hintNumber}>• </Text>{hint}</Text>)}
          </View>
        </View>

        <View style={webStyles.detailsCard}>
          <View style={webStyles.cardHeadingRow}>
            <Text style={webStyles.blueHeading}><FaIcon name="fa-file-alt" color={BLUE} /> VA Form Details</Text>
            <Text style={webStyles.sidPill}><FaIcon name="fa-clipboard-check" color={BLUE} /> SID: {workspace.case.va_sid}</Text>
          </View>
          <View style={webStyles.rule} />
          <View style={[webStyles.detailsGrid, !wide && { flexDirection: "column" }]}>
            <DetailsItem icon="fa-fingerprint" label="VA Form ID" value={workspace.case.instance_name} flex={2} />
            <DetailsItem icon="fa-code-branch" label="Project / Site" value={projectLabel} demo={workspace.case.is_demo_project} flex={2} />
            <DetailsItem icon="fa-user-clock" label="Age" value={age} flex={1} />
            <DetailsItem icon="fa-venus-mars" label="Gender" value={gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-"} flex={1} />
          </View>
        </View>

        <Pressable accessibilityRole="button" accessibilityState={{ expanded: categoriesOpen }} onPress={() => setCategoriesOpen((value) => !value)} style={[webStyles.mobileCategoryToggle, !wide && webStyles.mobileCategoryToggleShown, wide && webStyles.mobileCategoryToggleWide]}>
          <FaIcon name="fa-bars" color="#fff" /> <Text style={webStyles.mobileCategoryToggleText}>{categoriesOpen ? "Hide Categories" : "Show Categories"}</Text>
        </Pressable>

        <View style={[webStyles.workspaceGrid, !wide && webStyles.workspaceGridNarrow]}>
          <CategoryNavigation categories={categories} formId={workspace.case.instance_name} smartvaAvailable={workspace.smartva !== null} selectedCode={selectedCode} onSelectCategory={onSelectCategory} open={categoriesOpen || wide} narrow={!wide} setOpen={setCategoriesOpen} />
          <View style={webStyles.mainColumn}>
            <View style={webStyles.mainCard}>
              {categoryLoading ? <Text style={webStyles.muted}>Loading category…</Text> : null}
              {children}
              {categories.length > 1 ? <View style={webStyles.categoryPager}>
                <WebButton label="Previous" disabled={!previous} onPress={() => previous && onSelectCategory(previous.code)} />
                <WebButton label="Next" disabled={!next} onPress={() => next && onSelectCategory(next.code)} />
              </View> : null}
            </View>
          </View>
        </View>
      </View>
    </ScrollView>

    {notes ? <>
      <Pressable nativeID="digitva-notes-trigger" accessibilityRole="button" accessibilityLabel="Open Notes" onPress={() => setNotesOpen(true)} style={[webStyles.notesTab, notesOpen && webStyles.notesTabOpen]}>
        <FaIcon name="fa-paperclip" color="#fff" /> <Text style={webStyles.notesTabText}>Notes</Text>
      </Pressable>
      <View accessibilityLabel="Notes panel" style={[webStyles.notesPanel, notesOpen ? webStyles.notesPanelOpen : webStyles.notesPanelClosed]}>
        <View style={webStyles.notesHeader}><Text style={webStyles.notesTitle}><FaIcon name="fa-sticky-note" color="#fff" /> Notes / Observations</Text><Pressable nativeID="digitva-notes-close" accessibilityRole="button" accessibilityLabel="Close Notes" onPress={() => setNotesOpen(false)}><FaIcon name="fa-times" color="#fff" /></Pressable></View>
        <Text style={webStyles.noteFormId}>VA Form ID: {workspace.case.instance_name}</Text>
        <View style={webStyles.notesBody}>{notes}</View>
      </View>
    </> : null}
  </View>;
}

const webStyles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: PAGE, fontFamily: ROBOTO } as any,
  appHeader: { backgroundColor: BLUE, width: "100%", minHeight: 48 } as any,
  headerInner: { width: "100%", maxWidth: 1270, minHeight: 48, alignSelf: "center", paddingHorizontal: 12, flexDirection: "row", alignItems: "center", gap: 24, flexWrap: "wrap" } as any,
  logo: { width: 92, height: 40, backgroundColor: "#fff" } as any,
  headerLinks: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 18 },
  headerLink: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 12 },
  page: { paddingVertical: 16, paddingHorizontal: 16, alignItems: "center", backgroundColor: PAGE, minHeight: "100%" } as any,
  content: { width: "100%", maxWidth: 1270, gap: 24 } as any,
  hintsCard: { backgroundColor: CARD, padding: 24, borderRadius: 3, borderWidth: 1, borderColor: "#ededed", shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 4, shadowOffset: { width: 0, height: 2 }, gap: 10, minHeight: 199 } as any,
  detailsCard: { backgroundColor: CARD, padding: 24, borderRadius: 3, borderWidth: 1, borderColor: "#ededed", shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 4, shadowOffset: { width: 0, height: 2 }, gap: 12, minHeight: 206 } as any,
  cardHeadingRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" } as any,
  blueHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 18, lineHeight: 25 } as any,
  hintsHeading: { color: BLUE, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: 30 } as any,
  hintLead: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: 27.2, fontWeight: "700", marginTop: 4 } as any,
  hintList: { gap: 4, paddingLeft: 6 },
  hint: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: 27.2 },
  hintNumber: { color: BLUE, fontWeight: "700" },
  sidPill: { color: BLUE, fontFamily: ROBOTO, fontSize: 12, borderWidth: 1, borderColor: "#cbd8e8", borderRadius: radius.full, paddingVertical: 5, paddingHorizontal: 10, backgroundColor: "#f7faff", maxWidth: "100%", flexShrink: 1 } as any,
  rule: { height: 1, backgroundColor: BORDER },
  detailsGrid: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  detailItem: { backgroundColor: MUTED, borderRadius: 3, padding: 14, minHeight: 76, gap: 8 } as any,
  detailLabel: { flexDirection: "row", alignItems: "center", gap: 8 },
  detailLabelText: { color: "#5a6470", fontFamily: ROBOTO, fontSize: 13 },
  detailValue: { color: TEXT, fontFamily: ROBOTO, fontSize: 15, fontWeight: "700" },
  demo: { color: "#fff", backgroundColor: "#c92f3e", borderRadius: 3, fontSize: 10, fontWeight: "700", paddingVertical: 2, paddingHorizontal: 5, marginLeft: "auto" } as any,
  mobileCategoryToggle: { display: "none", backgroundColor: BLUE, minHeight: 44, borderRadius: 3, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 } as any,
  mobileCategoryToggleShown: { display: "flex" } as any,
  mobileCategoryToggleWide: { display: "none" } as any,
  mobileCategoryToggleText: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700" },
  workspaceGrid: { flexDirection: "row", alignItems: "flex-start", gap: 24 },
  workspaceGridNarrow: { flexDirection: "column" } as any,
  categoryColumn: { width: 299, minWidth: 260, gap: 16 },
  categoryColumnNarrow: { width: "100%", minWidth: 0 } as any,
  categoryColumnClosed: { display: "none" },
  categoryCard: { backgroundColor: CARD, borderWidth: 1, borderColor: BORDER, borderRadius: 3, overflow: "hidden" },
  categoryHeader: { backgroundColor: BLUE, minHeight: 38, paddingHorizontal: 14, flexDirection: "row", alignItems: "center", gap: 9 },
  categoryHeaderText: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 14 },
  categoryList: { gap: 0 },
  categoryItem: { minHeight: 52, paddingHorizontal: 12, borderBottomWidth: 1, borderBottomColor: "#edf0f3", flexDirection: "row", alignItems: "center", gap: 10 },
  categoryItemSelected: { backgroundColor: "#0d6efd", borderLeftWidth: 3, borderLeftColor: BLUE },
  categoryLabel: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, lineHeight: 27.2, flex: 1 },
  categoryLabelSelected: { color: "#fff", fontWeight: "700" },
  categoryBadge: { color: "#fff", backgroundColor: BLUE, borderRadius: 10, minWidth: 20, textAlign: "center", paddingHorizontal: 5, paddingVertical: 2, fontSize: 11, fontWeight: "700" } as any,
  attachmentBadge: { backgroundColor: "#eef1f4", borderRadius: 10, minWidth: 24, paddingHorizontal: 5, paddingVertical: 2, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4 } as any,
  attachmentBadgeText: { color: "#687482", fontFamily: ROBOTO, fontSize: 11, fontWeight: "700" },
  pressed: { opacity: 0.78 },
  empty: { color: "#687482", padding: 14, fontFamily: ROBOTO, fontSize: 13 },
  mainColumn: { flex: 1, minWidth: 0, gap: 16 },
  mainCard: { backgroundColor: CARD, borderWidth: 1, borderColor: BORDER, borderRadius: 3, overflow: "hidden", padding: 14, minHeight: 250 },
  muted: { color: "#687482", fontFamily: ROBOTO, fontSize: 14 },
  smartvaCard: { backgroundColor: CARD, borderWidth: 1, borderColor: BORDER, borderRadius: 3, padding: 14, gap: 8 },
  smartvaTitle: { color: TEXT, fontFamily: ROBOTO, fontSize: 17, fontWeight: "700" },
  smartvaText: { color: TEXT, fontFamily: ROBOTO, fontSize: 14, lineHeight: 21 },
  categoryPager: { flexDirection: "row", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: BORDER, paddingTop: 14, marginTop: 18 },
  notesTab: { position: "fixed", right: 0, top: "42%", backgroundColor: BLUE, paddingVertical: 12, paddingHorizontal: 8, borderTopLeftRadius: 4, borderBottomLeftRadius: 4, zIndex: 30, flexDirection: "row", alignItems: "center", gap: 5, transform: [{ rotate: "-90deg" }, { translateX: -30 }] } as any,
  notesTabOpen: { opacity: 0 },
  notesTabText: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 12 },
  notesPanel: { position: "fixed", right: 0, top: 0, bottom: 0, width: 360, maxWidth: "92%", backgroundColor: CARD, borderLeftWidth: 1, borderColor: BORDER, shadowColor: "#000", shadowOpacity: 0.18, shadowRadius: 12, shadowOffset: { width: -3, height: 0 }, zIndex: 29 } as any,
  notesPanelClosed: { display: "none" },
  notesPanelOpen: { display: "flex" },
  notesHeader: { minHeight: 54, paddingHorizontal: 16, backgroundColor: BLUE, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  notesTitle: { color: "#fff", fontFamily: ROBOTO, fontWeight: "700", fontSize: 15 },
  closeNotes: { color: "#fff", fontSize: 28, lineHeight: 28, paddingHorizontal: 8 },
  noteFormId: { color: "#687482", fontFamily: ROBOTO, fontSize: 12, padding: 12, borderBottomWidth: 1, borderBottomColor: BORDER },
  notesBody: { padding: 12, flex: 1 },
});
