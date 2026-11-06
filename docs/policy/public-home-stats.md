---
title: Public Home Page Overview and KPIs
doc_type: policy
status: active
owner: engineering
last_updated: 2026-11-06
---

# Public Home Page Overview and KPIs

Owner direction, 2026-11-06.

## Overview slides

The logged-out home page (`va_main.va_index`) shows an eight-slide DigitVA
overview, 15 seconds per slide (two minutes), in
`app/templates/va_frontpages/_overview_slides.html`. The slides describe platform
features only. They show no study results and no cause-of-death distribution.
Rotation stops on hover, on keyboard focus and on the Pause button, and never
starts when the visitor prefers reduced motion.

## KPIs

`app/services/public_home_stats_service.py` shows aggregate counts:
interviews, physician coders, interviews with a SmartVA result, interview
languages, and the distribution by language, age band and sex.

- **Which projects count:** only projects with the project setting
  `home_kpis_included` (Admin → Projects, "Included in homepage KPIs";
  default off, migration `e4b7c2d9a6f1`). The training project
  (`DIGITVA_TRAINING_PROJECT_ID`) and any project with Demo / Training or the
  synthetic demo reset are never counted. The admin API refuses to switch the
  setting on for them, and the service filters them out again.
- **No causes of death:** no cause-of-death or SmartVA cause distribution
  appears. Those analyses belong to the programmes' own publications.
- **Duplicates:** a confirmed duplicate submission is not counted.
- **Small cells:** a category with fewer than 5 deaths, or an unknown value,
  is folded into "Other or unknown".
- **Load:** the counts read the hourly analytics materialized views and are
  cached in Redis for 60 minutes. The logged-out page is sent with
  `Cache-Control: private, max-age=3600` and `Vary: Cookie`; a page carrying a
  flash message is not cached.

## Footer

The site footer states that the source code is open under the MIT licence,
while verbal autopsy data and content are not, and it links to the GitHub
repository.
