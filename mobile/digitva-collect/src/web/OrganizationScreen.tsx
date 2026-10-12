import { useEffect, useMemo, useState } from "react";
import { Text, View } from "react-native";

import { useAppState } from "../AppState";
import { ClientApiError } from "../client/api";
import { t } from "../i18n";
import { getMyOrganization, getUnitPeople, type BelowUnit, type OrgPerson, type OrgProject, type UnitPeople } from "../organization/api";
import { Button, useUiStyles } from "../ui";
import type { JsonRequester } from "../workspace/api";
import { createWebWorkspaceTransport } from "../workspace/transport.web";
import { browserErrorText, WebShell } from "./common";

/** A Below unit opened in place: its people and child units, or why they did not load. */
type OpenedUnit = { loading: boolean; error: string; detail?: UnitPeople };

/** Indent for nested child units, so each level reads as one step below its parent. */
const NESTED = { marginLeft: 16, gap: 4 };

function unitErrorText(error: unknown): string {
  if (error instanceof ClientApiError && error.status === 404) return t("orgUnitNotAllowed");
  return browserErrorText(error);
}

/** Name and cadre only: the API never sends contact details, and nothing else is shown. */
function PeopleList({ people }: { people: OrgPerson[] }) {
  const styles = useUiStyles();
  if (!people.length) return <Text style={styles.muted}>{t("orgNoPeople")}</Text>;
  return (
    <>
      {people.map((person, index) => (
        <Text key={`${index}-${person.name}`} style={styles.text}>
          {t("orgPersonLine", { name: person.name, cadre: person.cadre })}
        </Text>
      ))}
    </>
  );
}

function BelowUnits({
  units,
  opened,
  onToggle,
}: {
  units: BelowUnit[];
  opened: Record<string, OpenedUnit>;
  onToggle: (orgUnitId: string) => void;
}) {
  const styles = useUiStyles();
  if (!units.length) return <Text style={styles.muted}>{t("orgNone")}</Text>;
  return (
    <>
      {units.map((unit) => {
        const state = opened[unit.org_unit_id];
        // A unit whose load failed is not open: its button offers a retry.
        const expanded = Boolean(state && !state.error);
        return (
          <View key={unit.org_unit_id} style={styles.card}>
            <Text style={styles.text}>{t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })}</Text>
            <Text style={styles.muted}>{t("orgPeopleCount", { count: unit.people_count })}</Text>
            <Button
              kind="secondary"
              label={expanded ? t("orgClose") : t("orgOpen")}
              accessibilityLabel={expanded ? t("orgCloseUnit", { unit: unit.unit_name }) : t("orgOpenUnit", { unit: unit.unit_name })}
              expanded={expanded}
              loading={state?.loading}
              onPress={() => onToggle(unit.org_unit_id)}
            />
            {state?.error ? <Text style={styles.error} accessibilityRole="alert">{state.error}</Text> : null}
            {state?.detail ? (
              <View style={NESTED}>
                <PeopleList people={state.detail.people} />
                <BelowUnits units={state.detail.children} opened={opened} onToggle={onToggle} />
              </View>
            ) : null}
          </View>
        );
      })}
    </>
  );
}

/** A unit above, or the user's own level: the unit line, then its people. */
function UnitBlock({ name, level, people }: { name: string; level?: string; people: OrgPerson[] }) {
  const styles = useUiStyles();
  return (
    <View style={styles.card}>
      <Text style={styles.text}>{level ? t("orgUnitLine", { unit: name, level }) : name}</Text>
      <PeopleList people={people} />
    </View>
  );
}

/** Drops a closed unit and every unit opened beneath it, so reopening it shows its children collapsed. */
function dropUnitAndBelow(current: Record<string, OpenedUnit>, orgUnitId: string): Record<string, OpenedUnit> {
  const next = { ...current };
  const pending = [orgUnitId];
  while (pending.length) {
    const id = pending.pop()!;
    const detail = next[id]?.detail;
    delete next[id];
    for (const child of detail?.children ?? []) pending.push(child.org_unit_id);
  }
  return next;
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

          <Text style={styles.headline}>{t("orgWhereIAm")}</Text>
          {project.my_units.length === 0 ? <Text style={styles.muted}>{t("orgNoPlacement")}</Text> : null}
          {project.my_units.map((unit) => (
            <View key={unit.org_unit_id}>
              <Text style={styles.text}>{t("orgUnitLine", { unit: unit.unit_name, level: unit.level_name })}</Text>
              {unit.cadres.length ? <Text style={styles.muted}>{t("orgCadres", { cadres: unit.cadres.join(", ") })}</Text> : null}
            </View>
          ))}

          <Text style={styles.headline}>{t("orgAbove")}</Text>
          {project.above.length === 0 ? <Text style={styles.muted}>{t("orgNone")}</Text> : null}
          {project.above.map((unit) => (
            <UnitBlock key={unit.org_unit_id} name={unit.unit_name} level={unit.level_name} people={unit.people} />
          ))}

          <Text style={styles.headline}>{t("orgMyLevel")}</Text>
          {project.my_level.length === 0 ? <Text style={styles.muted}>{t("orgNone")}</Text> : null}
          {project.my_level.map((unit) => (
            <UnitBlock key={unit.org_unit_id} name={unit.unit_name} people={unit.people} />
          ))}

          <Text style={styles.headline}>{t("orgBelow")}</Text>
          <BelowUnits units={project.below} opened={opened} onToggle={(id) => void toggle(id)} />
        </View>
      ))}
    </WebShell>
  );
}
