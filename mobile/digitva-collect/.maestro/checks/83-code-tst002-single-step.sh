# Coding receipt, TST002: single step adds a final cause and no Step 1, so finals = Step 1s + 1
# whether or not 82 ran first; one narrative quality row. The social autopsy analysis exists only
# when the picked case had social autopsy answers (the flow skips it otherwise): reported, not asserted.
coder="u.email like 'e2e.${MAESTRO_RUN_ID}.coder@%'"
ini=$(dbq "select count(*) from va_initial_assessments a join va_users u on u.user_id = a.va_iniassess_by where $coder and a.va_iniassess_status::text = 'active'")
fin=$(dbq "select count(*) from va_final_assessments a join va_users u on u.user_id = a.va_finassess_by where $coder and a.va_finassess_status::text = 'active'")
nqa=$(dbq "select count(*) from va_narrative_assessments a join va_users u on u.user_id = a.va_nqa_by where $coder")
saa=$(dbq "select count(*) from va_social_autopsy_analyses a join va_users u on u.user_id = a.va_saa_by where $coder and a.va_saa_status::text = 'active'")
echo "server: e2e coder step 1 = $ini, final = $fin (expected step 1 + 1), nqa = $nqa (expected 1), social autopsy = $saa"
[ "$fin" = "$((ini + 1))" ] && [ "$nqa" = "1" ]
