# Coding receipt, TST001: the e2e coder has one active Step 1 and one active final cause on
# the server. Counts only, so which case the pool gave does not matter; no narrative quality
# row exists for this coder (NQA is off in TST001).
coder="u.email like 'e2e.${MAESTRO_RUN_ID}.coder@%'"
ini=$(dbq "select count(*) from va_initial_assessments a join va_users u on u.user_id = a.va_iniassess_by where $coder and a.va_iniassess_status::text = 'active'")
fin=$(dbq "select count(*) from va_final_assessments a join va_users u on u.user_id = a.va_finassess_by where $coder and a.va_finassess_status::text = 'active'")
nqa=$(dbq "select count(*) from va_narrative_assessments a join va_users u on u.user_id = a.va_nqa_by where $coder")
echo "server: e2e coder step 1 = $ini (expected 1), final = $fin (expected 1), nqa = $nqa (expected 0)"
[ "$ini" = "1" ] && [ "$fin" = "1" ] && [ "$nqa" = "0" ]
