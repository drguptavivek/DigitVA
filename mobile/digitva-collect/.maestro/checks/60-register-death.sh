# R01 server receipt: the reporter's registration is on the server exactly once.
n=$(dbq "select count(*) from va_death_register r join va_users u on u.user_id = r.registered_by where u.email like 'e2e.${MAESTRO_RUN_ID}.reporter@%'")
echo "server: deaths registered by the e2e reporter = $n (expected 2)"
[ "$n" = "2" ]
