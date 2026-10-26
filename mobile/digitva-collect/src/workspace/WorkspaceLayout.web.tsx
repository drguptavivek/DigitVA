import React, { useEffect, useRef, useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View, useWindowDimensions } from "react-native";

import { radius } from "../theme";
import { ensureVendorCss } from "./vendorCss.web";
import { useWebStyles, type WebPalette } from "./webPalette";
import { useScrollMemory } from "./useScrollMemory";
import type { WorkspaceLayoutProps } from "./WorkspaceLayout";
import { NotesCloseContext } from "./notesClose";

// react-dom ships without types here (no @types/react-dom); same hand-typed call as AppHeader.web.tsx.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createPortal } = require("react-dom") as { createPortal: (children: React.ReactNode, container: Element) => React.ReactElement };

/**
 * Renders fixed overlays (notes tab, notes and case-info panels) under document.body. react-native-web Views
 * create a stacking context, so inside the layout a fixed panel's z-index cannot beat the sticky app header;
 * at the root it can. Context still flows through a portal. Without a DOM (native-style test renderer) it is inline.
 */
function BodyOverlay({ children }: { children: React.ReactNode }) {
  const body = typeof document === "undefined" ? undefined : document.body;
  return body?.nodeType === 1 ? createPortal(children, body) : <>{children}</>;
}

const ROBOTO = "Roboto, Arial, sans-serif";
const WIDE_BREAKPOINT = 900;
// Below this the section rail is replaced by a hamburger that opens a left flyout.
const PHONE_BREAKPOINT = 768;

function FaIcon({ name, label, color }: { name: string; label?: string; color?: string }) {
  return React.createElement("i", {
    className: `fas ${name}`,
    style: color ? { color } : undefined,
    "aria-hidden": label ? undefined : true,
    "aria-label": label,
  });
}

function WebButton({ id, label, onPress, disabled = false, disabledReason }: { id?: string; label: string; onPress: () => void; disabled?: boolean; disabledReason?: string }) {
  const [webStyles, w] = useWebStyles(makeStyles);
  return React.createElement("button", {
    id,
    type: "button",
    disabled,
    onClick: onPress,
    "aria-label": disabledReason ? `${label}: ${disabledReason}` : undefined,
    title: disabledReason,
    style: {
      background: disabled ? w.disabledBg : w.card,
      border: `1px solid ${disabled ? w.disabledBorder : w.blue}`,
      borderRadius: 4,
      color: disabled ? w.disabledText : w.blue,
      cursor: disabled ? "default" : "pointer",
      fontFamily: ROBOTO,
      fontSize: 12,
      fontWeight: 600,
      minHeight: 44,
      padding: "6px 12px",
    },
  }, label);
}

type WebWorkspaceLayoutProps = WorkspaceLayoutProps & { nextBlockedReason?: string; smartvaPanel?: React.ReactNode };

function IcdBrowserLink({ classification }: { classification?: "icd10" | "icd11" | null }) {
  const [webStyles, w] = useWebStyles(makeStyles);
  const browser = classification === "icd11"
    ? { href: "https://icd.who.int/browse/2026-01/mms/en", label: "ICD-11 Browser" }
    : classification === "icd10"
      ? { href: "https://icd.who.int/browse10/2019/en", label: "ICD-10 Browser" }
      : null;
  if (!browser) return null;
  return <View style={webStyles.icdBrowserCard}>
    <a
      href={browser.href}
      target="_blank"
      rel="noopener noreferrer"
      title={`Open ${browser.label}`}
      aria-label={browser.label}
      style={webStyles.icdBrowserLink}
    ><FaIcon name="fa-book-medical" color={w.blue} /> {browser.label}</a>
  </View>;
}

function DetailsItem({ icon, label, value, demo, flex }: { icon: string; label: string; value: string; demo?: boolean; flex: number }) {
  const [webStyles, w] = useWebStyles(makeStyles);
  return <View style={[webStyles.detailItem, { flex }]}>
    <View style={webStyles.detailLabel}><FaIcon name={icon} color={w.blue} /><Text style={webStyles.detailLabelText}>{label}</Text>{demo ? <Text style={webStyles.demo}>DEMO</Text> : null}</View>
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
  icdClassification,
  selectedCode,
  onSelectCategory,
  open,
  narrow,
  phone,
  setOpen,
  smartvaPanel,
}: Pick<WorkspaceLayoutProps, "categories" | "selectedCode" | "onSelectCategory"> & { formId: string; smartvaAvailable: boolean; icdClassification?: "icd10" | "icd11" | null; open: boolean; narrow: boolean; phone: boolean; setOpen: (open: boolean) => void; smartvaPanel?: React.ReactNode }) {
  const [webStyles, w] = useWebStyles(makeStyles);
  const categoryItem = (item: (typeof categories)[number], compact: boolean) => {
    const selected = selectedCode === item.code;
    const attachmentCount = typeof (item as { attachment_count?: unknown }).attachment_count === "number"
      ? (item as { attachment_count: number }).attachment_count
      : 0;
    const countLabel = item.count && item.count > 0 ? `, ${item.count} responses` : "";
    const attachmentLabel = attachmentCount > 0 ? `, ${attachmentCount} attachments` : "";
    return <Pressable
      key={`${compact ? "rail" : "drawer"}-${item.code}`}
      accessibilityRole="button"
      accessibilityLabel={`${item.nav_label}${countLabel}${attachmentLabel}`}
      accessibilityState={{ selected }}
      onPress={() => { onSelectCategory(item.code); setOpen(false); }}
      style={({ pressed }) => [compact ? webStyles.categoryRailItem : webStyles.categoryItem, selected && webStyles.categoryItemSelected, pressed && webStyles.pressed]}
    >
      <FaIcon name={item.icon_name ?? "fa-folder-open"} color={selected ? w.onBar : w.blue} />
      {compact ? <Text style={webStyles.srOnly}>{item.nav_label}</Text> : <Text style={[webStyles.categoryLabel, selected && webStyles.categoryLabelSelected]}>{item.nav_label}</Text>}
      {!compact && item.count && item.count > 0 ? <Text style={webStyles.categoryBadge}>{item.count}</Text> : null}
      {!compact && attachmentCount > 0 ? <View style={webStyles.attachmentBadge} accessibilityLabel={`${attachmentCount} attachments`}><FaIcon name="fa-paperclip" color={w.textMuted} /><Text style={webStyles.attachmentBadgeText}>{attachmentCount}</Text></View> : null}
    </Pressable>;
  };

  const drawerA11y = narrow
    ? { role: "dialog", "aria-modal": true, "aria-label": "Case categories" }
    : { role: "complementary", "aria-label": "Case categories" };
  const drawer = <View nativeID="digitva-category-drawer" {...(drawerA11y as any)} style={[webStyles.categoryDrawer, !narrow && webStyles.categoryDrawerDesktop, narrow && webStyles.categoryDrawerNarrow]}>
    <View style={webStyles.categoryDrawerHeader}>
      <Text style={webStyles.categoryDrawerTitle}>{formId || "Categories"}</Text>
      <Pressable nativeID="digitva-category-drawer-close" accessibilityRole="button" accessibilityLabel="Close category names" onPress={() => setOpen(false)} style={webStyles.categoryDrawerClose}><FaIcon name="fa-times" color={w.blue} /></Pressable>
    </View>
    {categories.length ? categories.map((item) => categoryItem(item, false)) : <Text style={webStyles.empty}>No visible categories for this submission.</Text>}
    {!categories.some((c) => c.code === "smartva_section") ? (
      smartvaPanel ?? <View style={webStyles.smartvaCard}>
        <Text style={webStyles.smartvaTitle}><FaIcon name="fa-chart-pie" color={w.blue} /> SmartVA</Text>
        <Text style={webStyles.smartvaText}>{smartvaAvailable ? "Done (result shown in the assessment steps)" : "Results are shown in COD Assessment when available."}</Text>
      </View>
    ) : null}
    <IcdBrowserLink classification={icdClassification} />
  </View>;

  const layer = open ? <View style={narrow ? webStyles.categoryDrawerLayer : webStyles.categoryDrawerInline} {...(narrow ? { accessibilityViewIsModal: true } : {})}>
    {narrow ? <Pressable accessibilityRole="button" accessibilityLabel="Close category names" onPress={() => setOpen(false)} style={webStyles.categoryDrawerBackdrop} /> : null}
    {drawer}
  </View> : null;
  if (phone) return layer;

  return <View style={webStyles.categoryRailColumn}>
    <View nativeID="digitva-category-rail" style={webStyles.categoryRail} accessibilityLabel="Case category shortcuts">
      <Pressable
        nativeID="digitva-category-drawer-trigger"
        accessibilityRole="button"
        accessibilityLabel={open ? "Close category names" : "Open category names"}
        accessibilityState={{ expanded: open }}
        onPress={() => setOpen(!open)}
        style={webStyles.categoryRailMenu}
      ><FaIcon name={open ? "fa-times" : "fa-bars"} color={w.onBar} /></Pressable>
      {categories.map((item) => categoryItem(item, true))}
      {!categories.some((c) => c.code === "smartva_section") ? (
        <Pressable accessibilityRole="button" accessibilityLabel="Open SmartVA status" onPress={() => setOpen(true)} style={webStyles.smartvaRail}>
          <FaIcon name="fa-chart-pie" color={w.blue} />
          <Text style={webStyles.srOnly}>SmartVA: {smartvaAvailable ? "Done" : "Results available in COD Assessment when available"}</Text>
        </Pressable>
      ) : null}
    </View>
    {layer}
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
  nextBlockedReason,
  smartvaPanel,
}: WebWorkspaceLayoutProps) {
  const [webStyles, w] = useWebStyles(makeStyles);
  const { width } = useWindowDimensions();
  const wide = width >= WIDE_BREAKPOINT;
  const phone = width < PHONE_BREAKPOINT;
  const [categoriesOpen, setCategoriesOpen] = useState(false);
  const [infoOpen, setInfoOpen] = useState(false);
  const [notesOpen, setNotesOpen] = useState(false);
  const wasWide = useRef(wide);

  useEffect(() => {
    if (!wide && wasWide.current) {
      setCategoriesOpen(false);
    }
    wasWide.current = wide;
  }, [wide]);

  useEffect(() => {
    if (!infoOpen || typeof document === "undefined") return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setInfoOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [infoOpen]);

  useEffect(() => {
    if (!notesOpen || typeof document === "undefined") return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setNotesOpen(false);
      if (wide || event.key !== "Tab") return;
      const panel = document.getElementById("digitva-notes-panel");
      const focusable = panel?.querySelectorAll<HTMLElement>("button, a, [tabindex]:not([tabindex='-1'])");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    document.getElementById("digitva-notes-close")?.focus();
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [notesOpen, wide]);

  useEffect(() => {
    if (!categoriesOpen || typeof document === "undefined") return undefined;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCategoriesOpen(false);
      if (wide || event.key !== "Tab") return;
      const drawer = document.getElementById("digitva-category-drawer");
      const focusable = drawer?.querySelectorAll<HTMLElement>("button, a, [tabindex]:not([tabindex='-1'])");
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", closeOnEscape);
    document.getElementById("digitva-category-drawer-close")?.focus();
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [categoriesOpen, wide]);

  // Page behind the open drawer must not scroll; restore whatever the body had on close or unmount.
  useEffect(() => {
    if (!categoriesOpen || typeof document === "undefined") return undefined;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previous; };
  }, [categoriesOpen]);

  const categoryWasOpen = useRef(false);
  useEffect(() => {
    if (typeof document !== "undefined" && categoryWasOpen.current && !categoriesOpen) document.getElementById("digitva-category-drawer-trigger")?.focus();
    categoryWasOpen.current = categoriesOpen;
  }, [categoriesOpen, wide]);

  const notesWasOpen = useRef(false);
  useEffect(() => {
    if (typeof document !== "undefined" && notesWasOpen.current && !notesOpen) document.getElementById("digitva-notes-trigger")?.focus();
    notesWasOpen.current = notesOpen;
  }, [notesOpen]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    ensureVendorCss();
    if (!document.getElementById("digitva-workspace-scrollbars")) {
      const style = document.createElement("style");
      style.id = "digitva-workspace-scrollbars";
      style.textContent = "#digitva-category-rail::-webkit-scrollbar{width:0;height:0}";
      document.head.appendChild(style);
    }
  }, []);

  const scrollMemory = useScrollMemory(identity.mode, identity.vaSid, selectedCode);
  const selectedIndex = Math.max(0, categories.findIndex((item) => item.code === selectedCode));
  const previous = categories[selectedIndex - 1];
  const next = categories[selectedIndex + 1];
  const age = workspace.case.age === null || workspace.case.age === undefined ? "-" : String(workspace.case.age);
  const gender = workspace.case.gender ?? "-";
  const genderLabel = gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-";
  // Absent or null (older server, or a viewer whose tables redact it): no part, no placeholder.
  const district = workspace.case.survey_district?.trim() || null;
  const state = workspace.case.survey_state?.trim() || null;
  // One ellipsized line: a long state is cut first, so the district stays visible.
  const location = [district, state].filter(Boolean).join(", ");
  const infoLine = [`${age} y`, genderLabel, location].filter(Boolean).join(" · ");
  const infoLabel = `Age ${age}, ${genderLabel}${district ? `, Survey district ${district}` : ""}${state ? `, Survey state ${state}` : ""}`;
  const projectSite = `${workspace.case.project_code ?? "-"}/${workspace.case.site_code ?? "-"}`;
  const projectLabel = workspace.case.is_demo_project ? `${projectSite} - TESTING PROJECT` : projectSite;
  const hints = hintText(identity.mode);
  const hintsCard = <View style={webStyles.hintsCard}>
    <View style={webStyles.cardHeadingRow}>
      <Text style={webStyles.hintsHeading}><FaIcon name="fa-info-circle" color={w.blue} /> Hints</Text>
      <WebButton label="Back to Dashboard" onPress={onExit} />
    </View>
    <Text style={webStyles.hintLead}>{identity.mode === "reviewing" ? "Verbal Autopsy Quality Assurance" : identity.mode === "view" ? "Verbal Autopsy Submission (read-only)" : "Verbal Autopsy Cause of Death Ascertainment"}</Text>
    <View style={webStyles.hintList}>
      {hints.map((hint) => <Text key={hint} style={webStyles.hint}><Text style={webStyles.hintNumber}>• </Text>{hint}</Text>)}
    </View>
  </View>;
  const caseSummary = <View style={webStyles.caseSummary} accessibilityLabel={`Age ${age}, ${gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-"}${workspace.case.is_demo_project ? ", DEMO" : ""}`}>
    <Text style={webStyles.caseSummaryText}>Age {age}</Text>
    <Text style={webStyles.caseSummaryText}>{gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-"}</Text>
    {workspace.case.is_demo_project ? <Text style={webStyles.demo}>DEMO</Text> : null}
  </View>;
  const detailsCard = <View style={webStyles.detailsCard}>
    <View style={webStyles.cardHeadingRow}>
      <Text style={webStyles.blueHeading}><FaIcon name="fa-file-alt" color={w.blue} /> VA Form Details</Text>
      <Text style={webStyles.sidPill}><FaIcon name="fa-clipboard-check" color={w.blue} /> SID: {workspace.case.va_sid}</Text>
    </View>
    {caseSummary}
    <View style={webStyles.rule} />
    <View style={[webStyles.detailsGrid, !wide && { flexDirection: "column" }]}>
      <DetailsItem icon="fa-fingerprint" label="VA Form ID" value={workspace.case.instance_name} flex={2} />
      <DetailsItem icon="fa-code-branch" label="Project / Site" value={projectLabel} demo={workspace.case.is_demo_project} flex={2} />
      <DetailsItem icon="fa-user-clock" label="Age" value={age} flex={1} />
      <DetailsItem icon="fa-venus-mars" label="Gender" value={genderLabel} flex={1} />
      {district ? <DetailsItem icon="fa-map-marker-alt" label="Survey district" value={district} flex={2} /> : null}
      {state ? <DetailsItem icon="fa-map" label="Survey state" value={state} flex={2} /> : null}
    </View>
  </View>;

  return <View style={webStyles.safe}>
    <ScrollView {...scrollMemory} style={webStyles.scroller} contentContainerStyle={[webStyles.page, phone && webStyles.pagePhone, phone && notes ? webStyles.pageWithNotesPill : null]}>
      <View style={webStyles.content}>
        {phone ? <View style={[webStyles.sectionBar, categoriesOpen && webStyles.sectionBarBehind]}>
          <Pressable
            nativeID="digitva-category-drawer-trigger"
            accessibilityRole="button"
            accessibilityLabel="Open sections menu"
            accessibilityState={{ expanded: categoriesOpen }}
            onPress={() => setCategoriesOpen(true)}
            style={webStyles.sectionBarButton}
          ><FaIcon name="fa-bars" color={w.onBar} /></Pressable>
          <View style={webStyles.sectionBarText}>
            <Text numberOfLines={1} style={webStyles.sectionBarTitle}>{categories[selectedIndex]?.nav_label ?? ""}</Text>
            <Text numberOfLines={1} accessibilityLabel={infoLabel} style={webStyles.sectionBarInfo}>{infoLine}</Text>
          </View>
          <Pressable
            nativeID="digitva-case-info-trigger"
            accessibilityRole="button"
            accessibilityLabel="Open VA Form Details and Hints"
            onPress={() => setInfoOpen(true)}
            style={webStyles.sectionBarInfoBtn}
          >
            <FaIcon name="fa-info-circle" color={w.blue} />
            <Text style={webStyles.sectionBarInfoBtnText}>Case Info</Text>
          </Pressable>
        </View> : (
          <View style={webStyles.desktopTopActions}>
            <View nativeID="digitva-case-strip" style={webStyles.caseStrip}>
              {workspace.case.deceased_name ? <Text numberOfLines={1} style={webStyles.caseStripId}>{workspace.case.deceased_name}</Text> : null}
              <Text numberOfLines={1} style={workspace.case.deceased_name ? webStyles.caseStripText : webStyles.caseStripId}>{workspace.case.instance_name}</Text>
              <Text numberOfLines={1} accessibilityLabel={infoLabel} style={webStyles.caseStripText}>{infoLine}</Text>
              <Text numberOfLines={1} accessibilityLabel={`Project / Site ${projectSite}`} style={webStyles.caseStripText}>{projectSite}</Text>
              {workspace.case.is_demo_project ? <Text style={webStyles.demo}>DEMO</Text> : null}
            </View>
            <WebButton id="digitva-case-info-trigger" label="Case Info & Form Details" onPress={() => setInfoOpen(true)} />
            <WebButton label="Back to Dashboard" onPress={onExit} />
          </View>
        )}

      <View style={[webStyles.workspaceGrid, !wide && webStyles.workspaceGridNarrow]}>
          <CategoryNavigation categories={categories} formId={workspace.case.instance_name} smartvaAvailable={workspace.smartva_status === "done" || workspace.smartva !== null} icdClassification={workspace.case.icd_classification} selectedCode={selectedCode} onSelectCategory={onSelectCategory} open={categoriesOpen} narrow={!wide} phone={phone} setOpen={setCategoriesOpen} smartvaPanel={smartvaPanel} />
          <View style={webStyles.mainColumn}>
            <View style={[webStyles.mainCard, phone && webStyles.mainCardPhone]}>
              {categoryLoading ? <Text style={webStyles.muted}>Loading category…</Text> : null}
              {children}
              {categories.length > 1 ? <View style={webStyles.categoryPager}>
                <WebButton label="Previous" disabled={!previous} onPress={() => previous && onSelectCategory(previous.code)} />
                <View style={webStyles.nextControl}>
                  <WebButton label="Next" disabled={!next || Boolean(nextBlockedReason)} disabledReason={next ? nextBlockedReason : undefined} onPress={() => next && !nextBlockedReason && onSelectCategory(next.code)} />
                  {next && nextBlockedReason ? <Text accessibilityRole="alert" style={webStyles.nextBlockedReason}>{nextBlockedReason}</Text> : null}
                </View>
              </View> : null}
            </View>
          </View>
        </View>
      </View>
    </ScrollView>

    <BodyOverlay>
    {notes ? <>
      <Pressable nativeID="digitva-notes-trigger" accessibilityRole="button" accessibilityLabel="Open Notes" onPress={() => setNotesOpen(true)} style={[webStyles.notesTab, !wide && webStyles.notesTabMobile, (notesOpen || (phone && categoriesOpen)) && webStyles.notesTabOpen]}>
        <FaIcon name="fa-paperclip" color={w.onBar} /><Text style={webStyles.notesTabText}>Notes</Text>
      </Pressable>
      <View nativeID="digitva-notes-panel" {...((wide ? { role: "complementary", "aria-label": "Notes panel" } : { role: "dialog", "aria-modal": true, "aria-label": "Notes panel" }) as any)} style={[webStyles.notesPanel, !wide && webStyles.notesPanelMobile, notesOpen ? webStyles.notesPanelOpen : webStyles.notesPanelClosed]}>
        <View style={webStyles.notesHeader}><Text style={webStyles.notesTitle}><FaIcon name="fa-sticky-note" color={w.onBar} /> Notes / Observations</Text><Pressable nativeID="digitva-notes-close" accessibilityRole="button" accessibilityLabel="Close Notes" onPress={() => setNotesOpen(false)}><FaIcon name="fa-times" color={w.onBar} /></Pressable></View>
        <Text style={webStyles.noteFormId}>VA Form ID: {workspace.case.instance_name}</Text>
        <View style={webStyles.notesBody}><NotesCloseContext.Provider value={() => setNotesOpen(false)}>{notes}</NotesCloseContext.Provider></View>
      </View>
    </> : null}

    <View
      nativeID="digitva-case-info-panel"
      {...((wide ? { role: "complementary", "aria-label": "Case details and hints" } : { role: "dialog", "aria-modal": true, "aria-label": "Case details and hints" }) as any)}
      style={[webStyles.notesPanel, !wide && webStyles.notesPanelMobile, infoOpen ? webStyles.notesPanelOpen : webStyles.notesPanelClosed]}
    >
      <View style={webStyles.notesHeader}>
        <Text style={webStyles.notesTitle}><FaIcon name="fa-info-circle" color={w.onBar} /> VA Form Details & Hints</Text>
        <Pressable nativeID="digitva-case-info-close" accessibilityRole="button" accessibilityLabel="Close Case Details" onPress={() => setInfoOpen(false)}>
          <FaIcon name="fa-times" color={w.onBar} />
        </Pressable>
      </View>
      <ScrollView style={webStyles.infoPanelScroll} contentContainerStyle={webStyles.infoPanelContent}>
        <View style={webStyles.mobileCaseHeader}>
          {workspace.case.deceased_name ? <Text style={webStyles.mobileCaseId}>{workspace.case.deceased_name}</Text> : null}
          <Text style={workspace.case.deceased_name ? webStyles.mobileCaseMetaText : webStyles.mobileCaseId}>{workspace.case.instance_name}</Text>
          <View style={webStyles.mobileCaseMeta} accessibilityLabel={`Age ${age}, ${gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-"}${workspace.case.is_demo_project ? ", DEMO" : ""}`}>
            <Text style={webStyles.mobileCaseMetaText}>Age {age}</Text>
            <Text style={webStyles.mobileCaseMetaText}>{gender ? gender.charAt(0).toUpperCase() + gender.slice(1) : "-"}</Text>
            {workspace.case.is_demo_project ? <Text style={webStyles.demo}>DEMO</Text> : null}
          </View>
        </View>
        {detailsCard}
        {hintsCard}
      </ScrollView>
    </View>
    </BodyOverlay>
  </View>;
}

const makeStyles = (w: WebPalette) => StyleSheet.create({
  safe: { flex: 1, width: "100%", minHeight: 0, backgroundColor: w.page, fontFamily: ROBOTO } as any,
  page: { paddingVertical: 16, paddingHorizontal: 16, alignItems: "center", backgroundColor: w.page, minHeight: "100%", width: "100%", boxSizing: "border-box" } as any,
  content: { width: "100%", maxWidth: 1270, gap: 24 } as any,
  hintsCard: { backgroundColor: w.card, padding: 24, borderRadius: radius.lg, borderWidth: 1, borderColor: w.cardEdge, shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 4, shadowOffset: { width: 0, height: 2 }, gap: 10, minHeight: 199 } as any,
  detailsCard: { backgroundColor: w.card, padding: 24, borderRadius: radius.lg, borderWidth: 1, borderColor: w.cardEdge, shadowColor: "#000", shadowOpacity: 0.06, shadowRadius: 4, shadowOffset: { width: 0, height: 2 }, gap: 12, minHeight: 206 } as any,
  cardHeadingRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" } as any,
  blueHeading: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 18, lineHeight: 25 } as any,
  hintsHeading: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 24, lineHeight: 30 } as any,
  hintLead: { color: w.text, fontFamily: ROBOTO, fontSize: 16, lineHeight: 27.2, fontWeight: "700", marginTop: 4 } as any,
  hintList: { gap: 4, paddingLeft: 6 },
  hint: { color: w.text, fontFamily: ROBOTO, fontSize: 16, lineHeight: 27.2 },
  hintNumber: { color: w.blue, fontWeight: "700" },
  sidPill: { color: w.blue, fontFamily: ROBOTO, fontSize: 12, borderWidth: 1, borderColor: w.pillBorder, borderRadius: radius.full, paddingVertical: 5, paddingHorizontal: 10, backgroundColor: w.pillBg, maxWidth: "100%", flexShrink: 1 } as any,
  rule: { height: 1, backgroundColor: w.border },
  detailsGrid: { flexDirection: "row", gap: 12, flexWrap: "wrap" },
  detailItem: { backgroundColor: w.muted, borderRadius: radius.md, padding: 14, minHeight: 76, gap: 8 } as any,
  detailLabel: { flexDirection: "row", alignItems: "center", gap: 8 },
  detailLabelText: { color: w.textMuted, fontFamily: ROBOTO, fontSize: 12 },
  detailValue: { color: w.text, fontFamily: ROBOTO, fontSize: 14, fontWeight: "700" },
  demo: { color: w.onBar, backgroundColor: w.demo, borderRadius: radius.sm, fontSize: 12, fontWeight: "700", paddingVertical: 2, paddingHorizontal: 5, marginLeft: "auto" } as any,
  mobileCategoryToggle: { display: "none", backgroundColor: w.bar, minHeight: 44, borderRadius: radius.md, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 8 } as any,
  mobileCategoryToggleShown: { display: "flex" } as any,
  mobileCategoryToggleWide: { display: "none" } as any,
  mobileCategoryToggleText: { color: w.onBar, fontFamily: ROBOTO, fontWeight: "700" },
  workspaceGrid: { flexDirection: "row", alignItems: "flex-start", gap: 24 },
  workspaceGridNarrow: { flexDirection: "row", alignItems: "flex-start", gap: 10 } as any,
  mobileDisclosure: { gap: 8 },
  mobileCaseHeader: { backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, padding: 14, gap: 8 },
  mobileCaseId: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 18, lineHeight: 24 },
  mobileCaseMeta: { flexDirection: "row", gap: 18, flexWrap: "wrap" },
  mobileCaseMetaText: { color: w.text, fontFamily: ROBOTO, fontSize: 14, lineHeight: 20 },
  caseSummary: { flexDirection: "row", alignItems: "center", gap: 14, flexWrap: "wrap" },
  caseSummaryText: { color: w.text, fontFamily: ROBOTO, fontSize: 14, lineHeight: 20, fontWeight: "700" },
  mobileDisclosureButton: { minHeight: 44, paddingHorizontal: 14, backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  mobileDisclosureText: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 14 },
  categoryColumn: { width: 299, minWidth: 260, gap: 16 },
  categoryRailColumn: { width: 52, minWidth: 52, position: "sticky", top: 12, alignSelf: "flex-start", zIndex: 20 } as any,
  categoryRail: { width: 52, backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, maxHeight: "calc(100dvh - 72px)", overflowY: "auto", overflowX: "hidden", scrollbarWidth: "none", msOverflowStyle: "none", alignItems: "center" } as any,
  categoryRailMenu: { width: 50, minHeight: 48, backgroundColor: w.bar, alignItems: "center", justifyContent: "center" } as any,
  categoryRailItem: { width: 50, minHeight: 48, borderBottomWidth: 1, borderBottomColor: w.borderSoft, alignItems: "center", justifyContent: "center" } as any,
  smartvaRail: { width: 50, minHeight: 48, alignItems: "center", justifyContent: "center", borderTopWidth: 1, borderTopColor: w.borderSoft } as any,
  categoryDrawerLayer: { position: "fixed", left: 0, right: 0, top: 0, bottom: 0, zIndex: 50, flexDirection: "row" } as any,
  categoryDrawerInline: { position: "absolute", left: 58, top: 0, zIndex: 50 } as any,
  categoryDrawerBackdrop: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.36)" } as any,
  categoryDrawer: { width: 300, maxWidth: "84%", height: "100%", overflowY: "auto", backgroundColor: w.card, borderRightWidth: 1, borderRightColor: w.border, paddingTop: 12, zIndex: 51, shadowColor: "#000", shadowOpacity: 0.2, shadowRadius: 10, shadowOffset: { width: 3, height: 0 } } as any,
  categoryDrawerNarrow: { width: "80%", maxWidth: 320, paddingTop: "max(12px, env(safe-area-inset-top))", paddingBottom: "env(safe-area-inset-bottom)", paddingLeft: "env(safe-area-inset-left)" } as any,
  // Sticks to the top of the page scroller; solid page colour, below the drawer (50) and Notes panel (45, above the app header at 40).
  sectionBar: { flexDirection: "row", alignItems: "center", gap: 10, minHeight: 52, position: "sticky", top: 0, zIndex: 20, backgroundColor: w.page, marginHorizontal: -8, marginTop: -8, paddingHorizontal: 8, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: w.border, boxShadow: "0 2px 4px rgba(0,0,0,0.12)" } as any,
  // react-native-web gives the scroller a transform, which would make the fixed drawer scroll with the page.
  // overflowAnchor: late content above the viewport must not shift a restored offset.
  scroller: { transform: "none", overflowAnchor: "none" } as any,
  // The drawer layer lives in a lower stacking context than the bar (RNW views are z-index 0), so sink the bar while it is open.
  sectionBarBehind: { zIndex: 0 } as any,
  sectionBarButton: { width: 44, height: 44, borderRadius: 4, backgroundColor: w.bar, alignItems: "center", justifyContent: "center" } as any,
  sectionBarText: { flex: 1, minWidth: 0 } as any,
  sectionBarInfo: { color: w.textMuted, fontFamily: ROBOTO, fontSize: 12, lineHeight: 17 } as any,
  sectionBarTitle: { minWidth: 0, color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 16 } as any,
  sectionBarInfoBtn: { flexDirection: "row", alignItems: "center", gap: 6, minHeight: 36, paddingHorizontal: 10, paddingVertical: 6, borderRadius: 4, borderWidth: 1, borderColor: w.blue, backgroundColor: w.card } as any,
  sectionBarInfoBtnText: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 12 } as any,
  desktopTopActions: { flexDirection: "row", justifyContent: "flex-end", alignItems: "center", gap: 8, paddingRight: 88 } as any,
  // Always-visible case identity on desktop; the flyout keeps the full details and hints.
  caseStrip: { flex: 1, minWidth: 0, flexDirection: "row", alignItems: "center", gap: 14, minHeight: 44, paddingHorizontal: 12, backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg } as any,
  caseStripId: { flexShrink: 0, color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 14 } as any,
  caseStripText: { flexShrink: 1, minWidth: 0, color: w.text, fontFamily: ROBOTO, fontSize: 14 } as any,
  infoPanelScroll: { flex: 1 } as any,
  infoPanelContent: { padding: 12, gap: 12 } as any,
  pagePhone: { paddingHorizontal: 8, paddingVertical: 8 },
  pageWithNotesPill: { paddingBottom: 72 },
  mainCardPhone: { borderWidth: 0, borderRadius: 0, padding: 14, "--digitva-card-pad": "14px" } as any,
  categoryDrawerDesktop: { height: "auto", maxHeight: "78vh", maxWidth: 320, overflowY: "auto" } as any,
  categoryDrawerHeader: { minHeight: 48, paddingHorizontal: 16, flexDirection: "row", alignItems: "center", justifyContent: "space-between", borderBottomWidth: 1, borderBottomColor: w.border },
  categoryDrawerTitle: { color: w.blue, fontFamily: ROBOTO, fontWeight: "700", fontSize: 18 },
  categoryDrawerClose: { minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" } as any,
  srOnly: { position: "absolute", width: 1, height: 1, opacity: 0 } as any,
  categoryColumnClosed: { display: "none" },
  categoryCard: { backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, overflow: "hidden" },
  categoryHeader: { backgroundColor: w.bar, paddingHorizontal: 14, paddingVertical: 10, flexDirection: "row", alignItems: "center", gap: 9 },
  categoryHeaderText: { color: w.onBar, fontFamily: ROBOTO, fontWeight: "700", fontSize: 14, lineHeight: 20 },
  categoryList: { gap: 0 },
  categoryItem: { minHeight: 52, paddingHorizontal: 12, borderBottomWidth: 1, borderBottomColor: w.borderSoft, flexDirection: "row", alignItems: "center", gap: 10 },
  categoryItemSelected: { backgroundColor: w.selected, borderLeftWidth: 3, borderLeftColor: w.blue },
  categoryLabel: { color: w.text, fontFamily: ROBOTO, fontSize: 16, lineHeight: 27.2, flex: 1 },
  categoryLabelSelected: { color: w.onBar, fontWeight: "700" },
  categoryBadge: { color: w.onBar, backgroundColor: w.bar, borderRadius: radius.full, minWidth: 20, textAlign: "center", paddingHorizontal: 5, paddingVertical: 2, fontSize: 12, fontWeight: "700" } as any,
  attachmentBadge: { backgroundColor: w.chipBg, borderRadius: radius.full, minWidth: 24, paddingHorizontal: 5, paddingVertical: 2, flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 4 } as any,
  attachmentBadgeText: { color: w.textMuted, fontFamily: ROBOTO, fontSize: 12, fontWeight: "700" },
  pressed: { opacity: 0.78 },
  empty: { color: w.textMuted, padding: 14, fontFamily: ROBOTO, fontSize: 12 },
  mainColumn: { flex: 1, minWidth: 0, gap: 16 },
  mainCard: { backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, overflow: "hidden", padding: 14, minHeight: 250, "--digitva-card-pad": "14px" } as any,
  muted: { color: w.textMuted, fontFamily: ROBOTO, fontSize: 14 },
  smartvaCard: { backgroundColor: w.card, borderWidth: 1, borderColor: w.border, borderRadius: radius.lg, padding: 14, gap: 8 },
  smartvaTitle: { color: w.text, fontFamily: ROBOTO, fontSize: 16, fontWeight: "700" },
  smartvaText: { color: w.text, fontFamily: ROBOTO, fontSize: 14, lineHeight: 21 },
  categoryPager: { flexDirection: "row", justifyContent: "space-between", borderTopWidth: 1, borderTopColor: w.border, paddingTop: 14, marginTop: 18 },
  nextControl: { alignItems: "flex-end", gap: 6, maxWidth: "70%" } as any,
  nextBlockedReason: { color: w.blocked, fontFamily: ROBOTO, fontSize: 12, lineHeight: 17, textAlign: "right" },
  notesTab: { position: "fixed", right: 0, top: "42%", backgroundColor: w.bar, paddingVertical: 12, paddingHorizontal: 8, borderTopLeftRadius: 4, borderBottomLeftRadius: 4, zIndex: 46, flexDirection: "row", alignItems: "center", gap: 5, transform: [{ rotate: "-90deg" }, { translateX: -30 }] } as any,
  notesTabMobile: { top: "auto", bottom: "calc(12px + env(safe-area-inset-bottom))", right: 12, transform: [], minHeight: 44, borderRadius: radius.full, paddingVertical: 10, paddingHorizontal: 16, shadowColor: "#000", shadowOpacity: 0.3, shadowRadius: 6, shadowOffset: { width: 0, height: 2 } } as any,
  notesTabOpen: { opacity: 0, pointerEvents: "none" } as any,
  notesTabText: { color: w.onBar, fontFamily: ROBOTO, fontWeight: "700", fontSize: 12 },
  notesPanel: { position: "fixed", right: 0, top: 0, bottom: 0, width: 360, maxWidth: "92%", backgroundColor: w.card, borderLeftWidth: 1, borderColor: w.border, shadowColor: "#000", shadowOpacity: 0.18, shadowRadius: 12, shadowOffset: { width: -3, height: 0 }, zIndex: 45 } as any,
  notesPanelMobile: { left: 0, right: 0, top: "auto", bottom: 0, width: "100%", maxWidth: "100%", maxHeight: "82%", borderLeftWidth: 0, borderTopWidth: 1, shadowOffset: { width: 0, height: -3 } } as any,
  notesPanelClosed: { display: "none" },
  notesPanelOpen: { display: "flex" },
  notesHeader: { minHeight: 54, paddingHorizontal: 16, backgroundColor: w.bar, flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  notesTitle: { color: w.onBar, fontFamily: ROBOTO, fontWeight: "700", fontSize: 14 },
  closeNotes: { color: w.onBar, fontSize: 26, lineHeight: 28, paddingHorizontal: 8 },
  noteFormId: { color: w.textMuted, fontFamily: ROBOTO, fontSize: 12, padding: 12, borderBottomWidth: 1, borderBottomColor: w.border },
  notesBody: { padding: 12, flex: 1 },
  icdBrowserCard: { borderTopWidth: 1, borderTopColor: w.border, padding: 12 },
  icdBrowserLink: { minHeight: 44, paddingHorizontal: 12, paddingVertical: 10, borderWidth: 1, borderColor: w.blue, borderRadius: 4, color: w.blue, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontFamily: ROBOTO, fontSize: 14, fontWeight: "700", textDecorationLine: "none", boxSizing: "border-box" } as any,
});
