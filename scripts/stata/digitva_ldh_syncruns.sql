-- ODK synchronisation runs before the cut-off (de-identified: month and outcome only).
-- in_window = started on or after 31 March 2026 (the manuscript's reporting window).
copy (
  select to_char(started_at, 'YYYY-MM') as run_month,
         (started_at >= '2026-03-31')::int as in_window,
         triggered_by, status
  from va_sync_runs where started_at < '2026-06-01'
) to stdout with csv header;
