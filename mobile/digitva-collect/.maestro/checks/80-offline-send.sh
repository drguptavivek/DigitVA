# I09 server receipt: both e2e deaths now have their interview, and no death was
# duplicated by the retry.
sent=$(dbq "select count(*) from va_death_register r join va_users u on u.user_id = r.registered_by where u.email like 'e2e.${MAESTRO_RUN_ID}.reporter@%' and r.status <> 'registered'")
all=$(dbq "select count(*) from va_death_register r join va_users u on u.user_id = r.registered_by where u.email like 'e2e.${MAESTRO_RUN_ID}.reporter@%'")
echo "server: interviews received = $sent (expected 2), deaths = $all (expected 2)"
[ "$sent" = "2" ] && [ "$all" = "2" ]
