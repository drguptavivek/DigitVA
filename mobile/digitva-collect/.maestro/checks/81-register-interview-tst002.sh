# TST002 register-then-interview receipt: one case registered by the e2e reporter_t2 is on the server, submitted.
n=$(dbq "select count(*) from va_death_register r join va_users u on u.user_id = r.registered_by where u.email like 'e2e.${MAESTRO_RUN_ID}.reporter_t2@%' and r.project_id = 'TST002' and r.status = 'submitted'")
echo "server: TST002 submitted cases registered by the e2e reporter_t2 = $n (expected 1)"
[ "$n" = "1" ]
