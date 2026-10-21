use chrono::{DateTime, Utc};
use digitva_bundle::{
    ActingRole, DesignationSpec, RosterMember, RosterRoleGrant, StationCustodian,
};
use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use uuid::Uuid;

pub const DEFAULT_DESIGNATIONS: &[&str] = &[
    "Medical Officer",
    "Health Supervisor",
    "Health Worker / ANM / MPW",
    "Other",
];

pub const DEFAULT_DESIGNATION_SPECS: &[(&str, &str)] = &[
    ("medical_officer", "Medical Officer"),
    ("health_supervisor", "Health Supervisor"),
    ("health_worker", "Health Worker / ANM / MPW"),
    ("other", "Other"),
];

pub const VALID_ACTING_ROLES: &[&str] = &[
    "death_reporter",
    "interviewer",
    "station_supervisor",
    "coder",
];

/// Normalise canonical or legacy role names into the contract's canonical role codes:
/// `"death_reporter"`, `"interviewer"`, `"station_supervisor"`, `"coder"`.
pub fn normalise_acting_role(role: &str) -> Option<&'static str> {
    match role.trim() {
        "death_reporter" | "reporter" => Some("death_reporter"),
        "interviewer" => Some("interviewer"),
        "station_supervisor" | "supervisor" => Some("station_supervisor"),
        "coder" => Some("coder"),
        _ => None,
    }
}

pub fn designation_code_for_label(label_or_code: &str) -> String {
    let trimmed = label_or_code.trim();
    for &(code, label) in DEFAULT_DESIGNATION_SPECS {
        if trimmed.eq_ignore_ascii_case(code) || trimmed.eq_ignore_ascii_case(label) {
            return code.to_string();
        }
    }
    let mut slug = String::new();
    let mut last_underscore = false;
    for ch in trimmed.chars() {
        if ch.is_ascii_alphanumeric() {
            slug.push(ch.to_ascii_lowercase());
            last_underscore = false;
        } else if !last_underscore && !slug.is_empty() {
            slug.push('_');
            last_underscore = true;
        }
    }
    let slug = slug.trim_matches('_').to_string();
    if slug.is_empty() {
        "other".to_string()
    } else {
        slug
    }
}

pub fn designation_label_for_code(code_or_label: &str) -> String {
    let trimmed = code_or_label.trim();
    for &(code, label) in DEFAULT_DESIGNATION_SPECS {
        if trimmed.eq_ignore_ascii_case(code) || trimmed.eq_ignore_ascii_case(label) {
            return label.to_string();
        }
    }
    trimmed.to_string()
}

pub fn synthesize_sandbox_role_grants(
    project_id: &str,
    site_id: &str,
    is_reporter: bool,
    is_interviewer: bool,
    is_supervisor: bool,
    is_coder: bool,
) -> Vec<RosterRoleGrant> {
    let mut grants = Vec::new();
    if is_reporter {
        grants.push(RosterRoleGrant {
            role: ActingRole::DeathReporter,
            project_id: project_id.to_string(),
            site_id: site_id.to_string(),
            org_unit_id: None,
        });
    }
    if is_interviewer {
        grants.push(RosterRoleGrant {
            role: ActingRole::Interviewer,
            project_id: project_id.to_string(),
            site_id: site_id.to_string(),
            org_unit_id: None,
        });
    }
    if is_supervisor {
        grants.push(RosterRoleGrant {
            role: ActingRole::StationSupervisor,
            project_id: project_id.to_string(),
            site_id: site_id.to_string(),
            org_unit_id: None,
        });
    }
    if is_coder {
        grants.push(RosterRoleGrant {
            role: ActingRole::Coder,
            project_id: project_id.to_string(),
            site_id: site_id.to_string(),
            org_unit_id: None,
        });
    }
    grants
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StationRosterMember {
    pub member_id: String,
    pub user_id: Option<i64>,
    pub name: String,
    pub designation: String,
    #[serde(default)]
    pub roles: Vec<RosterRoleGrant>,
    pub is_reporter: bool,
    pub is_interviewer: bool,
    pub is_supervisor: bool,
    pub is_coder: bool,
    pub active: bool,
    pub source: String, // "sandbox" | "provisioned"
    pub created_at: String,
    pub updated_at: String,
}

impl StationRosterMember {
    pub fn allowed_acting_roles(&self) -> Vec<String> {
        let mut out = Vec::new();
        if self.is_reporter {
            out.push("death_reporter".to_string());
        }
        if self.is_interviewer {
            out.push("interviewer".to_string());
        }
        if self.is_supervisor {
            out.push("station_supervisor".to_string());
        }
        if self.is_coder {
            out.push("coder".to_string());
        }
        out
    }

    pub fn has_role_tick(&self, acting_role: &str) -> bool {
        match normalise_acting_role(acting_role) {
            Some("death_reporter") => self.is_reporter,
            Some("interviewer") => self.is_interviewer,
            Some("station_supervisor") => self.is_supervisor,
            Some("coder") => self.is_coder,
            _ => false,
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ActiveActorContext {
    pub member_id: String,
    pub user_id: Option<i64>,
    pub name: String,
    pub designation: String,
    pub acting_role: String, // "death_reporter" | "interviewer" | "station_supervisor" | "coder"
    pub allowed_acting_roles: Vec<String>,
    #[serde(default)]
    pub roles: Vec<RosterRoleGrant>,
}

impl ActiveActorContext {
    /// Formatted audit label carrying both roster person and acting role.
    pub fn audit_actor_label(&self) -> String {
        format!("{} ({}) [role:{}]", self.name, self.designation, self.acting_role)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RosterAuditEntry {
    pub audit_id: i64,
    pub action: String,
    pub target_member_id: Option<String>,
    pub actor_member_id: Option<String>,
    pub actor_name: String,
    pub acting_role: String,
    pub details: Value,
    pub created_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StationRosterSnapshot {
    pub station_mode: String,
    pub editable: bool,
    pub designations: Vec<String>,
    pub designation_specs: Vec<DesignationSpec>,
    pub custodian: Option<StationCustodian>,
    pub station_config_id: Option<String>,
    pub config_expires_at: Option<String>,
    pub days_until_expiry: Option<i64>,
    pub expiry_warning: bool,
    pub members: Vec<StationRosterMember>,
    pub active_actor: ActiveActorContext,
    pub recent_audit: Vec<RosterAuditEntry>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UpsertRosterMemberInput {
    #[serde(default)]
    pub member_id: Option<String>,
    #[serde(default)]
    pub user_id: Option<i64>,
    pub name: String,
    pub designation: String,
    #[serde(default)]
    pub roles: Vec<RosterRoleGrant>,
    #[serde(default)]
    pub is_reporter: bool,
    #[serde(default)]
    pub is_interviewer: bool,
    #[serde(default)]
    pub is_supervisor: bool,
    #[serde(default)]
    pub is_coder: bool,
    #[serde(default = "default_true")]
    pub active: bool,
}

fn default_true() -> bool {
    true
}

pub fn init_roster_tables_and_seed(conn: &Connection) -> rusqlite::Result<()> {
    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS loc_station_designations (
            designation TEXT PRIMARY KEY,
            code TEXT NOT NULL DEFAULT 'other',
            sort_order INTEGER NOT NULL DEFAULT 10
        );

        CREATE TABLE IF NOT EXISTS loc_station_roster (
            member_id TEXT PRIMARY KEY,
            user_id INTEGER,
            name TEXT NOT NULL,
            designation TEXT NOT NULL,
            roles_json TEXT NOT NULL DEFAULT '[]',
            is_reporter INTEGER NOT NULL DEFAULT 0 CHECK (is_reporter IN (0, 1)),
            is_interviewer INTEGER NOT NULL DEFAULT 0 CHECK (is_interviewer IN (0, 1)),
            is_supervisor INTEGER NOT NULL DEFAULT 0 CHECK (is_supervisor IN (0, 1)),
            is_coder INTEGER NOT NULL DEFAULT 0 CHECK (is_coder IN (0, 1)),
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            source TEXT NOT NULL DEFAULT 'sandbox' CHECK (source IN ('sandbox', 'provisioned')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS loc_station_active_actor (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active_member_id TEXT NOT NULL,
            acting_role TEXT NOT NULL CHECK (acting_role IN (
                'death_reporter', 'interviewer', 'station_supervisor', 'coder',
                'reporter', 'supervisor'
            )),
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS loc_station_roster_audit (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            action TEXT NOT NULL,
            target_member_id TEXT,
            actor_member_id TEXT,
            actor_name TEXT NOT NULL,
            acting_role TEXT NOT NULL,
            details_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        ",
    )?;

    let desig_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM loc_station_designations", [], |r| r.get(0))?;
    if desig_count == 0 {
        for (idx, &(code, label)) in DEFAULT_DESIGNATION_SPECS.iter().enumerate() {
            conn.execute(
                "INSERT INTO loc_station_designations (designation, code, sort_order) VALUES (?1, ?2, ?3)",
                params![label, code, (idx as i64 + 1) * 10],
            )?;
        }
    }

    let roster_count: i64 =
        conn.query_row("SELECT COUNT(*) FROM loc_station_roster", [], |r| r.get(0))?;
    let now = Utc::now().to_rfc3339();
    if roster_count == 0 {
        let mo_roles = serde_json::to_string(&synthesize_sandbox_role_grants(
            "1", "PHC01", true, true, true, true,
        ))
        .unwrap_or_else(|_| "[]".to_string());
        let hs_roles = serde_json::to_string(&synthesize_sandbox_role_grants(
            "1", "PHC01", true, true, true, false,
        ))
        .unwrap_or_else(|_| "[]".to_string());
        let hw_roles = serde_json::to_string(&synthesize_sandbox_role_grants(
            "1", "PHC01", true, true, false, false,
        ))
        .unwrap_or_else(|_| "[]".to_string());

        conn.execute(
            "INSERT INTO loc_station_roster (
                member_id, user_id, name, designation, roles_json,
                is_reporter, is_interviewer, is_supervisor, is_coder,
                active, source, created_at, updated_at
             ) VALUES
             ('roster-mo-1', NULL, 'Dr. Anil Sharma', 'Medical Officer', ?1, 1, 1, 1, 1, 1, 'sandbox', ?4, ?4),
             ('roster-hs-1', NULL, 'Sunita Devi', 'Health Supervisor', ?2, 1, 1, 1, 0, 1, 'sandbox', ?4, ?4),
             ('roster-hw-1', NULL, 'Rekha Kumari', 'Health Worker / ANM / MPW', ?3, 1, 1, 0, 0, 1, 'sandbox', ?4, ?4)",
            params![mo_roles, hs_roles, hw_roles, now],
        )?;
    }

    conn.execute(
        "INSERT OR IGNORE INTO loc_station_active_actor (id, active_member_id, acting_role, updated_at)
         VALUES (1, 'roster-mo-1', 'station_supervisor', ?1)",
        params![now],
    )?;

    Ok(())
}

pub fn list_designation_specs(conn: &Connection) -> Vec<DesignationSpec> {
    let Ok(mut stmt) = conn.prepare(
        "SELECT code, designation FROM loc_station_designations ORDER BY sort_order ASC, designation ASC",
    ) else {
        return DEFAULT_DESIGNATION_SPECS
            .iter()
            .map(|&(code, label)| DesignationSpec {
                code: code.to_string(),
                label: label.to_string(),
            })
            .collect();
    };
    let rows: Vec<DesignationSpec> = stmt
        .query_map([], |r| {
            let code: String = r.get(0)?;
            let label: String = r.get(1)?;
            Ok(DesignationSpec { code, label })
        })
        .ok()
        .into_iter()
        .flatten()
        .filter_map(Result::ok)
        .collect();
    if rows.is_empty() {
        DEFAULT_DESIGNATION_SPECS
            .iter()
            .map(|&(code, label)| DesignationSpec {
                code: code.to_string(),
                label: label.to_string(),
            })
            .collect()
    } else {
        rows
    }
}

pub fn list_designations(conn: &Connection) -> Vec<String> {
    list_designation_specs(conn)
        .into_iter()
        .map(|d| d.label)
        .collect()
}

pub fn list_roster_members(conn: &Connection) -> Vec<StationRosterMember> {
    let Ok(mut stmt) = conn.prepare(
        "SELECT member_id, user_id, name, designation, roles_json,
                is_reporter, is_interviewer, is_supervisor, is_coder,
                active, source, created_at, updated_at
         FROM loc_station_roster
         ORDER BY active DESC, COALESCE(user_id, 999999999) ASC, created_at ASC, member_id ASC",
    ) else {
        return Vec::new();
    };
    stmt.query_map([], |r| {
        let is_reporter = r.get::<_, i32>(5)? == 1;
        let is_interviewer = r.get::<_, i32>(6)? == 1;
        let is_supervisor = r.get::<_, i32>(7)? == 1;
        let is_coder = r.get::<_, i32>(8)? == 1;
        let roles_raw: String = r.get(4)?;
        let mut roles: Vec<RosterRoleGrant> =
            serde_json::from_str(&roles_raw).unwrap_or_default();
        if roles.is_empty() {
            roles = synthesize_sandbox_role_grants(
                "1",
                "PHC01",
                is_reporter,
                is_interviewer,
                is_supervisor,
                is_coder,
            );
        }
        Ok(StationRosterMember {
            member_id: r.get(0)?,
            user_id: r.get(1)?,
            name: r.get(2)?,
            designation: r.get(3)?,
            roles,
            is_reporter,
            is_interviewer,
            is_supervisor,
            is_coder,
            active: r.get::<_, i32>(9)? == 1,
            source: r.get(10)?,
            created_at: r.get(11)?,
            updated_at: r.get(12)?,
        })
    })
    .ok()
    .into_iter()
    .flatten()
    .filter_map(Result::ok)
    .collect()
}

pub fn find_roster_member<'a>(
    members: &'a [StationRosterMember],
    id_or_user_id: &str,
) -> Option<&'a StationRosterMember> {
    let trimmed = id_or_user_id.trim();
    members.iter().find(|m| {
        if m.member_id == trimmed {
            return true;
        }
        if let Some(uid) = m.user_id {
            if uid.to_string() == trimmed || format!("user-{uid}") == trimmed {
                return true;
            }
        }
        false
    })
}

pub fn get_active_actor(conn: &Connection) -> ActiveActorContext {
    let members = list_roster_members(conn);
    let stored: Option<(String, String)> = conn
        .query_row(
            "SELECT active_member_id, acting_role FROM loc_station_active_actor WHERE id = 1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?)),
        )
        .optional()
        .ok()
        .flatten();

    if let Some((mid, raw_role)) = stored {
        let norm_role = normalise_acting_role(&raw_role).unwrap_or("death_reporter");
        if let Some(m) = find_roster_member(&members, &mid).filter(|m| m.active) {
            let allowed = m.allowed_acting_roles();
            let effective_role = if m.has_role_tick(norm_role) {
                norm_role.to_string()
            } else {
                allowed
                    .first()
                    .cloned()
                    .unwrap_or_else(|| "death_reporter".to_string())
            };
            return ActiveActorContext {
                member_id: m.member_id.clone(),
                user_id: m.user_id,
                name: m.name.clone(),
                designation: m.designation.clone(),
                acting_role: effective_role,
                allowed_acting_roles: allowed,
                roles: m.roles.clone(),
            };
        }
    }

    // Fallback to first active member on roster
    if let Some(first) = members.iter().find(|m| m.active) {
        let allowed = first.allowed_acting_roles();
        let role = allowed
            .first()
            .cloned()
            .unwrap_or_else(|| "death_reporter".to_string());
        return ActiveActorContext {
            member_id: first.member_id.clone(),
            user_id: first.user_id,
            name: first.name.clone(),
            designation: first.designation.clone(),
            acting_role: role,
            allowed_acting_roles: allowed,
            roles: first.roles.clone(),
        };
    }

    ActiveActorContext {
        member_id: "roster-mo-1".to_string(),
        user_id: None,
        name: "Dr. Anil Sharma".to_string(),
        designation: "Medical Officer".to_string(),
        acting_role: "station_supervisor".to_string(),
        allowed_acting_roles: vec![
            "death_reporter".to_string(),
            "interviewer".to_string(),
            "station_supervisor".to_string(),
            "coder".to_string(),
        ],
        roles: synthesize_sandbox_role_grants("1", "PHC01", true, true, true, true),
    }
}

pub fn get_roster_snapshot(conn: &Connection, station_mode: &str) -> StationRosterSnapshot {
    let designation_specs = list_designation_specs(conn);
    let designations: Vec<String> = designation_specs.iter().map(|d| d.label.clone()).collect();
    let members = list_roster_members(conn);
    let active_actor = get_active_actor(conn);

    let meta: Option<(Option<String>, Option<String>, Option<String>)> = conn
        .query_row(
            "SELECT station_config_id, config_expires_at, custodian_json FROM loc_station_config WHERE id = 1",
            [],
            |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
        )
        .optional()
        .ok()
        .flatten();

    let (station_config_id, config_expires_at, custodian) = match meta {
        Some((cid, exp, cust_raw)) => {
            let cust: Option<StationCustodian> = cust_raw
                .and_then(|s| serde_json::from_str(&s).ok());
            (cid, exp, cust)
        }
        None => (None, None, None),
    };

    let (days_until_expiry, expiry_warning) = match config_expires_at
        .as_deref()
        .and_then(|s| DateTime::parse_from_rfc3339(s).ok())
    {
        Some(exp_dt) => {
            let rem = exp_dt.with_timezone(&Utc) - Utc::now();
            (Some(rem.num_days()), rem <= chrono::Duration::days(30))
        }
        None => (None, false),
    };

    let mut recent_audit = Vec::new();
    if let Ok(mut stmt) = conn.prepare(
        "SELECT audit_id, action, target_member_id, actor_member_id, actor_name,
                acting_role, details_json, created_at
         FROM loc_station_roster_audit
         ORDER BY audit_id DESC LIMIT 30",
    ) {
        if let Ok(rows) = stmt.query_map([], |r| {
            let raw_details: String = r.get(6)?;
            Ok(RosterAuditEntry {
                audit_id: r.get(0)?,
                action: r.get(1)?,
                target_member_id: r.get(2)?,
                actor_member_id: r.get(3)?,
                actor_name: r.get(4)?,
                acting_role: r.get(5)?,
                details: serde_json::from_str(&raw_details).unwrap_or_else(|_| json!({})),
                created_at: r.get(7)?,
            })
        }) {
            recent_audit = rows.filter_map(Result::ok).collect();
        }
    }

    StationRosterSnapshot {
        station_mode: station_mode.to_string(),
        editable: station_mode == "standalone",
        designations,
        designation_specs,
        custodian,
        station_config_id,
        config_expires_at,
        days_until_expiry,
        expiry_warning,
        members,
        active_actor,
        recent_audit,
    }
}

pub fn append_roster_audit(
    conn: &Connection,
    action: &str,
    target_member_id: Option<&str>,
    actor: &ActiveActorContext,
    details: Value,
) {
    let now = Utc::now().to_rfc3339();
    let details_str = serde_json::to_string(&details).unwrap_or_else(|_| "{}".to_string());
    let _ = conn.execute(
        "INSERT INTO loc_station_roster_audit (
            action, target_member_id, actor_member_id, actor_name, acting_role, details_json, created_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            action,
            target_member_id,
            actor.member_id,
            actor.name,
            actor.acting_role,
            details_str,
            now
        ],
    );
}

pub fn switch_active_actor(
    conn: &Connection,
    member_id: &str,
    requested_acting_role: Option<&str>,
) -> Result<ActiveActorContext, String> {
    let members = list_roster_members(conn);
    let Some(target) = find_roster_member(&members, member_id) else {
        return Err(format!("Roster member '{member_id}' not found."));
    };
    if !target.active {
        return Err(format!(
            "Roster member '{}' is currently deactivated.",
            target.name
        ));
    }

    let allowed = target.allowed_acting_roles();
    if allowed.is_empty() {
        return Err(format!(
            "Roster member '{}' has no role ticks enabled.",
            target.name
        ));
    }

    let acting_role = match requested_acting_role {
        Some(r) if !r.trim().is_empty() => {
            let Some(canon) = normalise_acting_role(r) else {
                return Err(format!("Invalid acting role '{r}'."));
            };
            if !target.has_role_tick(canon) {
                return Err(format!(
                    "'{}' does not have the '{}' role enabled on the station roster.",
                    target.name, canon
                ));
            }
            canon.to_string()
        }
        _ => allowed[0].clone(),
    };

    let now = Utc::now().to_rfc3339();
    conn.execute(
        "INSERT INTO loc_station_active_actor (id, active_member_id, acting_role, updated_at)
         VALUES (1, ?1, ?2, ?3)
         ON CONFLICT(id) DO UPDATE SET
            active_member_id = excluded.active_member_id,
            acting_role = excluded.acting_role,
            updated_at = excluded.updated_at",
        params![target.member_id, acting_role, now],
    )
    .map_err(|e| e.to_string())?;

    let updated = get_active_actor(conn);
    append_roster_audit(
        conn,
        "acting_role_switched",
        Some(&updated.member_id),
        &updated,
        json!({
            "member_id": updated.member_id,
            "user_id": updated.user_id,
            "name": updated.name,
            "designation": updated.designation,
            "acting_role": updated.acting_role
        }),
    );

    Ok(updated)
}

pub fn replace_provisioned_roster(
    conn: &Connection,
    designations: &[DesignationSpec],
    roster: &[RosterMember],
) -> rusqlite::Result<ActiveActorContext> {
    if !designations.is_empty() {
        conn.execute("DELETE FROM loc_station_designations", [])?;
        for (idx, d) in designations.iter().enumerate() {
            conn.execute(
                "INSERT OR IGNORE INTO loc_station_designations (designation, code, sort_order) VALUES (?1, ?2, ?3)",
                params![d.label, d.code, (idx as i64 + 1) * 10],
            )?;
        }
    }

    conn.execute("DELETE FROM loc_station_roster", [])?;
    let now = Utc::now().to_rfc3339();
    for m in roster {
        let is_reporter = m
            .roles
            .iter()
            .any(|g| g.role == ActingRole::DeathReporter);
        let is_interviewer = m.roles.iter().any(|g| g.role == ActingRole::Interviewer);
        let is_supervisor = m
            .roles
            .iter()
            .any(|g| g.role == ActingRole::StationSupervisor);
        let is_coder = m.roles.iter().any(|g| g.role == ActingRole::Coder);
        let roles_json = serde_json::to_string(&m.roles).unwrap_or_else(|_| "[]".to_string());
        let desig_label = designation_label_for_code(&m.designation);
        let member_id = format!("user-{}", m.user_id);

        conn.execute(
            "INSERT INTO loc_station_roster (
                member_id, user_id, name, designation, roles_json,
                is_reporter, is_interviewer, is_supervisor, is_coder,
                active, source, created_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'provisioned', ?11, ?11)",
            params![
                member_id,
                m.user_id,
                m.name,
                desig_label,
                roles_json,
                i32::from(is_reporter),
                i32::from(is_interviewer),
                i32::from(is_supervisor),
                i32::from(is_coder),
                i32::from(m.active),
                now
            ],
        )?;
    }

    let members = list_roster_members(conn);
    if let Some(first_active) = members.iter().find(|m| m.active) {
        let role = first_active
            .allowed_acting_roles()
            .first()
            .cloned()
            .unwrap_or_else(|| "death_reporter".to_string());
        conn.execute(
            "INSERT INTO loc_station_active_actor (id, active_member_id, acting_role, updated_at)
             VALUES (1, ?1, ?2, ?3)
             ON CONFLICT(id) DO UPDATE SET
                active_member_id = excluded.active_member_id,
                acting_role = excluded.acting_role,
                updated_at = excluded.updated_at",
            params![first_active.member_id, role, now],
        )?;
    }

    Ok(get_active_actor(conn))
}

pub fn upsert_sandbox_roster_member(
    conn: &Connection,
    station_mode: &str,
    input: &UpsertRosterMemberInput,
) -> Result<StationRosterMember, (u16, String)> {
    if station_mode != "standalone" {
        return Err((
            403,
            "Station roster is read-only when provisioned by the server.".to_string(),
        ));
    }

    let name = input.name.trim();
    if name.is_empty() {
        return Err((422, "Roster member name is required.".to_string()));
    }
    let designation = input.designation.trim();
    if designation.is_empty() {
        return Err((422, "Designation is required.".to_string()));
    }

    let mut is_reporter = input.is_reporter;
    let mut is_interviewer = input.is_interviewer;
    let mut is_supervisor = input.is_supervisor;
    let mut is_coder = input.is_coder;

    for r in &input.roles {
        match r.role {
            ActingRole::DeathReporter => is_reporter = true,
            ActingRole::Interviewer => is_interviewer = true,
            ActingRole::StationSupervisor => is_supervisor = true,
            ActingRole::Coder => is_coder = true,
        }
    }

    if !(is_reporter || is_interviewer || is_supervisor || is_coder) {
        return Err((
            422,
            "At least one role tick (Reporter, Interviewer, Supervisor, or Coder) must be selected."
                .to_string(),
        ));
    }

    // Ensure designation exists in loc_station_designations
    let designations = list_designations(conn);
    if !designations.iter().any(|d| d == designation) {
        let next_order = (designations.len() as i64 + 1) * 10;
        let code = designation_code_for_label(designation);
        let _ = conn.execute(
            "INSERT OR IGNORE INTO loc_station_designations (designation, code, sort_order) VALUES (?1, ?2, ?3)",
            params![designation, code, next_order],
        );
    }

    let actor = get_active_actor(conn);
    let now = Utc::now().to_rfc3339();
    let is_new = input
        .member_id
        .as_ref()
        .map(|s| s.trim().is_empty())
        .unwrap_or(true);
    let member_id = input
        .member_id
        .clone()
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| format!("roster-{}", &Uuid::new_v4().to_string()[..8]));

    let roles = if input.roles.is_empty() {
        synthesize_sandbox_role_grants(
            "1",
            "PHC01",
            is_reporter,
            is_interviewer,
            is_supervisor,
            is_coder,
        )
    } else {
        input.roles.clone()
    };
    let roles_json = serde_json::to_string(&roles).unwrap_or_else(|_| "[]".to_string());

    conn.execute(
        "INSERT INTO loc_station_roster (
            member_id, user_id, name, designation, roles_json,
            is_reporter, is_interviewer, is_supervisor, is_coder,
            active, source, created_at, updated_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, 'sandbox', ?11, ?11)
         ON CONFLICT(member_id) DO UPDATE SET
            user_id = excluded.user_id,
            name = excluded.name,
            designation = excluded.designation,
            roles_json = excluded.roles_json,
            is_reporter = excluded.is_reporter,
            is_interviewer = excluded.is_interviewer,
            is_supervisor = excluded.is_supervisor,
            is_coder = excluded.is_coder,
            active = excluded.active,
            updated_at = excluded.updated_at",
        params![
            member_id,
            input.user_id,
            name,
            designation,
            roles_json,
            i32::from(is_reporter),
            i32::from(is_interviewer),
            i32::from(is_supervisor),
            i32::from(is_coder),
            i32::from(input.active),
            now
        ],
    )
    .map_err(|e| (500, e.to_string()))?;

    append_roster_audit(
        conn,
        if is_new {
            "member_added"
        } else {
            "member_updated"
        },
        Some(&member_id),
        &actor,
        json!({
            "name": name,
            "designation": designation,
            "is_reporter": is_reporter,
            "is_interviewer": is_interviewer,
            "is_supervisor": is_supervisor,
            "is_coder": is_coder,
            "active": input.active
        }),
    );

    let members = list_roster_members(conn);
    members
        .into_iter()
        .find(|m| m.member_id == member_id)
        .ok_or_else(|| (500, "Failed to load saved roster member.".to_string()))
}

pub fn update_sandbox_designations(
    conn: &Connection,
    station_mode: &str,
    designations: &[String],
) -> Result<Vec<String>, (u16, String)> {
    if station_mode != "standalone" {
        return Err((
            403,
            "Designation list is read-only when provisioned by the server.".to_string(),
        ));
    }

    let cleaned: Vec<String> = designations
        .iter()
        .map(|s| s.trim().to_string())
        .filter(|s| !s.is_empty())
        .collect();
    if cleaned.is_empty() {
        return Err((422, "At least one designation is required.".to_string()));
    }

    let actor = get_active_actor(conn);
    conn.execute("DELETE FROM loc_station_designations", [])
        .map_err(|e| (500, e.to_string()))?;
    for (idx, d) in cleaned.iter().enumerate() {
        let code = designation_code_for_label(d);
        conn.execute(
            "INSERT OR IGNORE INTO loc_station_designations (designation, code, sort_order) VALUES (?1, ?2, ?3)",
            params![d, code, (idx as i64 + 1) * 10],
        )
        .map_err(|e| (500, e.to_string()))?;
    }

    append_roster_audit(
        conn,
        "designations_updated",
        None,
        &actor,
        json!({ "designations": cleaned }),
    );

    Ok(list_designations(conn))
}
