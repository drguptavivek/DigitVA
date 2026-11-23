# S05 server receipt: exactly one supervisor_correction by this run's supervisor (the left edit sent nothing).
n=$(dbq "select count(*) from va_submission_payload_versions v join va_users u on u.user_id = v.created_by where v.revision_reason_code = 'supervisor_correction' and u.email like 'e2e.${MAESTRO_RUN_ID}.supervisor@%'")
echo "server: supervisor corrections by the e2e supervisor = $n (expected 1)"
[ "$n" = "1" ]
