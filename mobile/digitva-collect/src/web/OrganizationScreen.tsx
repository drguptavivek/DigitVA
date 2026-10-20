import { useEffect, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { ClientApiError } from "../client/api";
import { t } from "../i18n";
import { getMyOrganization, getUnitPeople, type OrgProject } from "../organization/api";
import { spacing } from "../theme";
import { useUiStyles } from "../ui";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { browserErrorText, WebShell } from "./common";
import { ContextualHelpBanner } from "./ContextualHelp";
import { Chevron, FoldButton } from "./Chevron";
import { dropUnitAndBelow, OrgTree, roleNames, type OpenedUnit } from "./OrgTree";

function unitErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.status === 404) return t("orgUnitNotAllowed");
  return browserErrorText(error);
}

/** One line of where the user holds which role: whole project, then each own unit, then each site. */
function roleSummary(project: OrgProject): string {
  const positions = project.my_positions;
  const parts: string[] = [];
  if (positions?.project_roles.length) parts.push(t("orgWholeProject", { roles: roleNames(positions.project_roles) }));
  for (const unit of project.my_units) {
    if (unit.roles?.length) parts.push(t("orgRolesAt", { roles: roleNames(unit.roles.map((r) => r.role)), place: unit.unit_name }));
  }
  for (const site of positions?.sites ?? []) parts.push(t("orgRolesAt", { roles: roleNames(site.roles), place: site.site_name }));
  return parts.join("; ");
}

/** Only project-level roles: nothing to place in the card body beyond the summary, so it starts folded. */
function onlyProjectRoles(project: OrgProject): boolean {
  return Boolean(project.my_positions) && project.my_units.length === 0 && !project.my_positions?.sites.length;
}

/** The user's position and roles in every project they hold a grant in: one card per project. */
export default function OrganizationScreen() {
  const { bootstrap } = useAppState();
  const styles = useUiStyles();
  const request: JsonRequester | undefined = useMemo(
    () => (bootstrap ? createWebWorkspaceTransport(bootstrap.csrf) : undefined),
    [bootstrap],
  );
  const [projects, setProjects] = useState<OrgProject[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [opened, setOpened] = useState<Record<string, OpenedUnit>>({});
  /** Cards the user folded or unfolded; the rest follow `onlyProjectRoles`. */
  const [folded, setFolded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!request) return undefined;
    let active = true;
    getMyOrganization(request)
      .then((rows) => {
        if (active) setProjects(rows);
      })
      .catch((caught) => {
        if (active) setError(browserErrorText(caught));
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [request]);

  if (!bootstrap) return <WebShell title={t("organizationTitle")}>{null}</WebShell>;

  async function toggle(orgUnitId: string) {
    const state = opened[orgUnitId];
    if (state && !state.error) {
      setOpened((current) => dropUnitAndBelow(current, orgUnitId));
      return;
    }
    if (!request) return;
    setOpened((current) => ({ ...current, [orgUnitId]: { loading: true, error: "" } }));
    try {
      const detail = await getUnitPeople(request, orgUnitId);
      // Skip the reply when the unit was closed while it loaded.
      setOpened((current) => (current[orgUnitId] ? { ...current, [orgUnitId]: { loading: false, error: "", detail } } : current));
    } catch (caught) {
      setOpened((current) => (current[orgUnitId] ? { ...current, [orgUnitId]: { loading: false, error: unitErrorText(caught) } } : current));
    }
  }

  return (
    <WebShell title={t("organizationTitle")}>
      <ContextualHelpBanner screen="organization" />
      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!busy && !error && projects.length === 0 ? <Text style={styles.muted}>{t("orgNoProjects")}</Text> : null}
      {projects.map((project) => {
        const isFolded = folded[project.project_id] ?? onlyProjectRoles(project);
        const heading = t("orgProjectHeader", { name: project.project_name, code: project.project_id });
        const summary = roleSummary(project);
        const sites = project.my_positions?.sites ?? [];
        return (
          <View key={project.project_id} style={styles.card}>
            <FoldButton
              label={isFolded ? t("orgShowProject", { project: heading }) : t("orgHideProject", { project: heading })}
              expanded={!isFolded}
              onPress={() => setFolded((current) => ({ ...current, [project.project_id]: !isFolded }))}
              style={{ flexDirection: "row", alignItems: "center", gap: spacing.xs, minHeight: 44 }}
            >
              <View style={{ flex: 1, gap: spacing.xxs }}>
                <Text style={styles.headline}>{heading}</Text>
                {summary ? <Text style={styles.muted}>{summary}</Text> : null}
              </View>
              <Chevron expanded={!isFolded} />
            </FoldButton>
            {isFolded ? null : (
              <>
                {sites.length ? (
                  <View style={{ gap: spacing.xxs }}>
                    <Text style={styles.text}>{t("orgSitesHeading")}</Text>
                    {sites.map((site) => (
                      <Text key={site.site_id} style={styles.text}>
                        {`${site.site_name} · ${t("orgYouRoles", { roles: roleNames(site.roles) })}`}
                      </Text>
                    ))}
                  </View>
                ) : null}
                {project.has_tree === false ? null : (
                  <>
                    {project.my_units.length === 0 && !summary ? <Text style={styles.muted}>{t("orgNoPlacement")}</Text> : null}
                    <OrgTree project={project} opened={opened} onToggle={(id) => void toggle(id)} />
                  </>
                )}
              </>
            )}
          </View>
        );
      })}
    </WebShell>
  );
}
