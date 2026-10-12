import { useEffect, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { ClientApiError } from "../client/api";
import { t } from "../i18n";
import { getMyOrganization, getUnitPeople, type OrgProject } from "../organization/api";
import { Button, useUiStyles } from "../ui";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { browserErrorText, WebShell } from "./common";
import { dropUnitAndBelow, OrgTree, type OpenedUnit } from "./OrgTree";

function unitErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.status === 404) return t("orgUnitNotAllowed");
  return browserErrorText(error);
}

/** Where the signed-in user sits in the organization tree of each project they hold a grant in. */
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
      {busy ? <Text style={styles.muted}>{t("loading")}</Text> : null}
      {error ? <Text style={styles.error} accessibilityRole="alert">{error}</Text> : null}
      {!busy && !error && projects.length === 0 ? <Text style={styles.muted}>{t("orgNotInTree")}</Text> : null}
      {projects.map((project) => (
        <View key={project.project_id} style={styles.card}>
          {projects.length > 1 ? <Text style={styles.headline}>{project.project_name}</Text> : null}

          {project.my_units.length === 0 ? <Text style={styles.muted}>{t("orgNoPlacement")}</Text> : null}
          <OrgTree project={project} opened={opened} onToggle={(id) => void toggle(id)} />
        </View>
      ))}
    </WebShell>
  );
}
