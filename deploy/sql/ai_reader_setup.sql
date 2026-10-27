-- AI analytics reader role and digitva_ai_run(), for a database whose app user
-- cannot create them (migration a9e4c7f2b3d6 skips them with a warning).
-- Run once as a superuser against the app database:
--   psql -v app_user=digitva_app -d <app database> -f deploy/sql/ai_reader_setup.sql
-- Idempotent. Keep identical to READER_SETUP_SQL in
-- app/services/ai_analytics_sandbox.py (tests/services/test_ai_analytics_sandbox.py checks),
-- where the GRANT goes to current_user instead of :"app_user".
\set ON_ERROR_STOP on
DO $$
BEGIN
    CREATE ROLE digitva_ai_reader NOLOGIN;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
SELECT format('GRANT digitva_ai_reader TO %I', :'app_user') \gexec
DO $$
BEGIN
    GRANT SET ON PARAMETER temp_file_limit TO digitva_ai_reader;
EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;
END $$;
DROP FUNCTION IF EXISTS digitva_ai_run(text);
CREATE OR REPLACE FUNCTION digitva_ai_run(query text, max_bytes integer DEFAULT 1048576)
RETURNS SETOF json
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
SET work_mem = '16MB'
SET temp_file_limit = '256MB'
AS $fn$
DECLARE
    r json;
    total bigint := 0;
    cap bigint := least(max_bytes, 1048576);
BEGIN
    FOR r IN EXECUTE 'SELECT to_json(q) FROM (' || query || E'\n) q LIMIT 501' LOOP
        total := total + octet_length(r::text);
        IF total > cap THEN
            RAISE EXCEPTION 'The result is larger than % bytes.', cap USING ERRCODE = '54D01';
        END IF;
        RETURN NEXT r;
    END LOOP;
END
$fn$;
ALTER FUNCTION digitva_ai_run(text, integer) OWNER TO digitva_ai_reader;
REVOKE ALL ON FUNCTION digitva_ai_run(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION digitva_ai_run(text, integer) TO digitva_ai_reader;
