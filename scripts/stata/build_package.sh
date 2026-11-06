#!/usr/bin/env bash
# Builds the de-identified LDH analysis package in private/digitva-ldh-data/ and runs
# the Stata analysis from inside it. Run from anywhere; needs the dev DB (docker compose up).
set -euo pipefail
cd "$(dirname "$0")/../.."
pkg=private/digitva-ldh-data
mkdir -p "$pkg/data" "$pkg/output"
psql_run() { docker compose exec -T minerva_db_service psql -U minerva -d minerva -q -f - ; }
psql_run < scripts/stata/digitva_ldh_export.sql  > "$pkg/data/digitva_ldh_cases.csv"
psql_run < scripts/stata/digitva_ldh_syncruns.sql > "$pkg/data/digitva_ldh_syncruns.csv"
cp scripts/stata/digitva_ldh_analysis.do "$pkg/"
cp scripts/stata/README.md scripts/stata/pipeline.md "$pkg/"
cd "$pkg"
/Applications/Stata/StataSE.app/Contents/MacOS/stata-se -b do digitva_ldh_analysis.do
rm -f digitva_ldh_analysis.log   # batch mode log; the do file writes output/digitva_ldh_analysis.log
echo "Done: $pkg/output/"
