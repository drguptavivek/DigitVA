# I01 server receipt: the completed interview arrived. Exactly one of the e2e reporter's
# registered deaths is "submitted" (a complete interview; Finish as incomplete would
# leave "paused"), and the other is still "registered" for 80-offline-send.
n=$(dbq "select count(*) from va_death_register r join va_users u on u.user_id = r.registered_by where u.email like 'e2e.${MAESTRO_RUN_ID}.reporter@%' and r.status = 'submitted'")
echo "server: e2e deaths with a completed interview = $n (expected 1)"
[ "$n" = "1" ]
