-- Read-only pre-deploy count for migration f3c9d1a7b5e2 (digitva-l2dg).
--
-- After the migration, a WHO_2022_VA case whose current payload holds any
-- social autopsy (sa*) answer, in a project with Collect and Coder Social
-- Autopsy on, needs the coder's Social Autopsy analysis before final COD
-- (and the reviewer's, when Reviewer Social Autopsy is also on). This counts
-- the cases still open on each side and how many have no analysis yet.
-- Counts per project only: no identifiers, no payload values.
--
-- Run: psql -v ON_ERROR_STOP=1 -f scripts/l2dg_inflight_social_autopsy.sql
BEGIN READ ONLY;

WITH cases AS (
    SELECT p.project_id,
           p.reviewer_social_autopsy_enabled AS reviewer_on,
           w.workflow_state,
           s.va_sid,
           s.active_payload_version_id
    FROM va_submissions s
    JOIN va_forms f ON f.form_id = s.va_form_id
    JOIN mas_form_types ft ON ft.form_type_id = f.form_type_id
    JOIN va_project_master p ON p.project_id = f.project_id
    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
    JOIN va_submission_payload_versions v
      ON v.payload_version_id = s.active_payload_version_id
    WHERE ft.form_type_code = 'WHO_2022_VA'
      AND p.social_autopsy_collect_enabled
      AND p.social_autopsy_enabled
      AND EXISTS (SELECT 1 FROM jsonb_object_keys(v.payload_data) k
                  WHERE k LIKE 'sa%' AND k NOT LIKE 'sas%')
),
analysed AS (
    SELECT DISTINCT a.va_sid, a.payload_version_id
    FROM va_social_autopsy_analyses a
    WHERE a.va_saa_status = 'active'
)
SELECT c.project_id,
       count(*) FILTER (WHERE c.workflow_state IN
           ('screening_pending', 'attachment_sync_pending', 'smartva_pending',
            'ready_for_coding'))                                  AS coder_waiting,
       count(*) FILTER (WHERE c.workflow_state IN
           ('coding_in_progress', 'coder_step1_saved'))           AS coder_in_progress,
       count(*) FILTER (WHERE c.workflow_state IN
           ('screening_pending', 'attachment_sync_pending', 'smartva_pending',
            'ready_for_coding', 'coding_in_progress', 'coder_step1_saved')
           AND a.va_sid IS NULL)                                  AS coder_open_without_analysis,
       count(*) FILTER (WHERE c.reviewer_on AND c.workflow_state IN
           ('reviewer_eligible', 'reviewer_coding_in_progress'))  AS reviewer_open,
       count(*)                                                   AS all_cases_with_sa_answers
FROM cases c
LEFT JOIN analysed a
  ON a.va_sid = c.va_sid AND a.payload_version_id = c.active_payload_version_id
GROUP BY c.project_id
ORDER BY c.project_id;

ROLLBACK;
