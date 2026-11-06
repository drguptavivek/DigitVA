-- De-identified analysis file for the DigitVA LDH manuscript (one row per submission).
-- No identifiers, names, narratives or free text leave the database; the coder is a
-- per-project pseudonym. Output stays in private/ (git-ignored).
-- Run: docker compose exec -T minerva_db_service psql -U minerva -d minerva -q -f - < scripts/stata/digitva_ldh_export.sql > private/ldh-analysis/digitva_ldh_cases.csv
set statement_timeout = '300s';
-- ICD-10 code to WHO 2022 VA cause bucket (field and its category), as the
-- reporting layer resolves it: three-character code, legacy aliases applied.
create temp table bm as
  select m.icd_code as code, n.node_code as bucket, c.node_code as cat
  from map_icd_cod_buckets m
  join mas_cod_bucket_schemes s using (scheme_id)
  join mas_cod_bucket_nodes n on n.node_id = m.node_id
  left join mas_cod_bucket_nodes c on c.node_id = n.parent_node_id
  where s.scheme_code = 'WHO_2022_VA' and m.is_active and m.age_scope is null
    and m.icd_classification = 'icd10';
insert into bm
  select a.legacy_code, bm.bucket, bm.cat
  from map_icd10_legacy_reporting_aliases a join bm on bm.code = a.reporting_code
  where not exists (select 1 from bm x where x.code = a.legacy_code);
copy (
with base as (
  select s.va_sid, f.project_id, s.va_submission_date, s.va_narration_language lang,
         s.va_deceased_age_normalized_years age_y, v.payload_data pd
  from va_submissions s
  join va_forms f on f.form_id = s.va_form_id
  join va_submission_payload_versions v on v.va_sid = s.va_sid and v.version_status = 'active'
  where f.project_id in ('UNSW01', 'ICMR01')
    and s.va_submission_date < '2026-06-01'
), fa as (
  select va_sid, va_finassess_by, va_finassess_createdat, va_conclusive_cod
  from va_final_assessments
  where va_finassess_status = 'active' and va_finassess_createdat < '2026-06-01'
), ia as (
  -- Step 1 (SmartVA masked): the underlying cause is the last line of the sequence.
  select distinct on (va_sid) va_sid,
         upper(substring(coalesce(nullif(trim(va_antecedent_cod), ''), va_immediate_cod) from '^([A-Za-z][0-9]{2})')) as c1
  from va_initial_assessments where va_iniassess_status = 'active'
  order by va_sid, va_iniassess_createdat desc
), sv as (
  select distinct on (va_sid) va_sid, upper(left(va_smartva_cause1icd, 3)) as cs
  from va_smartva_results where va_smartva_status = 'active' and va_smartva_outcome = 'success'
  order by va_sid, va_smartva_addedat desc
)
select
  case b.project_id when 'UNSW01' then 1 else 2 end as version,
  (fa.va_sid is not null)::int as coded,
  to_char(b.va_submission_date, 'YYYY-MM') as sub_month,
  to_char(fa.va_finassess_createdat, 'YYYY-MM-DD') as coded_date,
  dense_rank() over (partition by b.project_id order by md5(fa.va_finassess_by::text)) * (fa.va_sid is not null)::int as coder,
  case when b.pd->>'Id10012' ~ '^\d{4}-\d\d-\d\d' and b.pd->>'Id10023' ~ '^\d{4}-\d\d-\d\d'
       then left(b.pd->>'Id10012', 10)::date - left(b.pd->>'Id10023', 10)::date end as death_to_interview_d,
  round((extract(epoch from fa.va_finassess_createdat - b.va_submission_date) / 86400)::numeric, 3) as sub_to_final_d,
  round((extract(epoch from fa.va_finassess_createdat - (
      select max(a.va_allocation_createdat) from va_allocations a
      where a.va_sid = b.va_sid and a.va_allocation_for = 'coding' and not a.va_allocation_training
        and a.va_allocation_createdat <= fa.va_finassess_createdat)) / 60)::numeric, 2) as coding_min,
  coalesce(nullif(b.lang, ''), 'unknown') as lang,
  case when b.age_y is null then 0 when b.age_y < 15 then 1 when b.age_y < 70 then 2 else 3 end as ageband,
  case when b.pd->>'Id10058' in ('hospital', 'other_health_facility') then 1
       when b.pd->>'Id10058' = 'home' then 2 else 3 end as place,
  length(trim(coalesce(b.pd->>'Id10476', ''))) as narr_chars,
  -- Written narrative class: 0 empty or placeholder (na, no, '.', single letters,
  -- 'no information'), 1 pointer to an uploaded photo ('as uploaded above', 'upload',
  -- 'अपलोड', misspellings), 2 short statement under 100 characters (mostly a cause
  -- only, e.g. 'old age'), 3 narrative of 100 characters or more.
  case
    when lower(trim(coalesce(b.pd->>'Id10476', ''))) ~ '^([[:punct:][:space:]]*|[a-z]{1,2}|n/?a|nil|none|no information( available)?|not available)$' then 0
    when lower(trim(b.pd->>'Id10476')) ~ '(upload|uplod|uploded|aplod|अपलोड|^update$|as attached|see (photo|image|attached))' then 1
    when length(trim(b.pd->>'Id10476')) < 100 then 2
    else 3 end as narr_class,
  (nullif(trim(coalesce(b.pd->>'imagenarr', '')), '') is not null)::int as narr_image,
  (nullif(trim(coalesce(b.pd->>'Id10476_audio', '')), '') is not null)::int as narr_audio,
  (select count(*) from generate_series(1, 30) i
     where nullif(trim(coalesce(b.pd->>('md_im' || i), '')), '') is not null) as doc_pages,
  (upper(substring(fa.va_conclusive_cod from '^[A-Za-z]')) = 'R')::int as ill_defined,
  (exists (select 1 from va_coder_review cr where cr.va_sid = b.va_sid))::int as flagged,
  (exists (select 1 from va_final_assessments d where d.va_sid = b.va_sid and d.va_finassess_status = 'deactive'
             and d.demo_expires_at is null and not coalesce(d.is_tester, false)))::int as recoded,
  (select count(*) from va_submission_payload_versions p where p.va_sid = b.va_sid) as payload_versions,
  (select count(*) from va_submission_payload_versions p where p.va_sid = b.va_sid and p.version_status = 'rejected') as rejected_versions,
  (select count(*) from va_submission_attachments t where t.va_sid = b.va_sid) as attachments,
  -- Later version from ODK: compare the first and second payload versions.
  -- odk_edited = ODK Central edit (new instanceID); answer_changes = questionnaire
  -- fields (Id1*, sa*, md_*, narrative image) that differ.
  coalesce(ch.odk_edited, 0) as odk_edited,
  coalesce(ch.answer_changes, 0) as answer_changes,
  -- Step 1 to Step 2 and SmartVA, by WHO 2022 VA cause bucket. Missing when
  -- a step or bucket is missing.
  (ia.c1 is not null and fa.va_sid is not null)::int as two_step,
  (upper(substring(fa.va_conclusive_cod from '^([A-Za-z][0-9]{2})')) <> ia.c1)::int as s12_code_chg,
  (b1.bucket <> b2.bucket)::int as s12_bucket_chg,
  (b1.cat <> b2.cat)::int as s12_cat_chg,
  (b1.bucket = bs.bucket)::int as s1_sv_agree,
  (b2.bucket = bs.bucket)::int as s2_sv_agree,
  (sv.cs like 'R%')::int as sv_undetermined
from base b left join fa on fa.va_sid = b.va_sid
left join ia on ia.va_sid = fa.va_sid
left join sv on sv.va_sid = b.va_sid
left join bm b1 on b1.code = ia.c1
left join bm b2 on b2.code = upper(substring(fa.va_conclusive_cod from '^([A-Za-z][0-9]{2})'))
left join bm bs on bs.code = sv.cs
left join lateral (
  select max((k = 'instanceID')::int) as odk_edited,
         count(*) filter (where k ~ '^(Id1|sa[0-9_]|md_|imagenarr|narr_)') as answer_changes
  from (select v1.payload_data d1, v2.payload_data d2
        from (select payload_data, row_number() over (order by version_created_at) rn
              from va_submission_payload_versions where va_sid = b.va_sid) v1
        join (select payload_data, row_number() over (order by version_created_at) rn
              from va_submission_payload_versions where va_sid = b.va_sid) v2 on v1.rn = 1 and v2.rn = 2) pr,
       lateral (select key k from jsonb_each(pr.d1) union select key from jsonb_each(pr.d2)) ks
  where pr.d1 -> ks.k is distinct from pr.d2 -> ks.k
) ch on true
order by 1, random()
) to stdout with csv header;

-- Synchronisation runs before the cut-off:
-- docker compose exec -T minerva_db_service psql -U minerva -d minerva -q -c "copy (select to_char(started_at,'YYYY-MM') as run_month, triggered_by, status from va_sync_runs where started_at < '2026-06-01') to stdout with csv header" > private/ldh-analysis/digitva_ldh_syncruns.csv
