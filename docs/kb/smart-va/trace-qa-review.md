---
title: SmartVA Trace QA Review
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# SmartVA Trace QA Review

This document began as the second-pass QA review after the initial `WHO_2022_VA_SOCIAL` tracing pass.

A third-pass deep trace has now been completed for every doc that was previously marked partial, helper-dependent, cross-subcategory, or free-text-branch-only.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Uncategorized And System Fields](uncategorized-system-fields.md)
- [SmartVA Agentic Tracing Instructions](agentic-tracing-instructions.md)
- [Trace Summary Matrix](trace-summary-matrix.md)

## Third-Pass Resolution Summary

| KB doc | Previous QA status | Third-pass result |
|---|---|---|
| [Duration Of Illness](duration-of-illness.md) | partial | completed; child/neonate helper path is explicit and adult visible WHO 2022 mapping is explicitly absent in this fork |
| [Chest Pain](chest-pain.md) | partial | completed; presence and duration are explicitly wired, while activity/location remain downstream-only without visible WHO 2022 mappings |
| [Headache](headache.md) | partial | completed; downstream adult symptom family exists, but no visible WHO 2022 adapter path is surfaced |
| [Mental Confusion](mental-confusion.md) | partial | completed; downstream adult symptom family exists, but no visible WHO 2022 adapter path is surfaced |
| [Stiff Neck](stiff-neck.md) | partial | completed; adult/child presence is explicit and adult duration is explicitly not wired from visible WHO 2022 fields |
| [Swelling](swelling.md) | partial | completed; adult puffiness/body-swelling path is explicit, and visible leg/feet-swelling fields are explicitly not wired in this fork |
| [Neonatal Delivery](neonatal-delivery.md) | partial | completed; explicit visible retained subset separated from downstream features fed by hidden or other-subcategory fields |
| [Neonatal Unresponsive](neonatal-unresponsive.md) | partial | completed; `Id10281` retained directly, and `Id10282`/`Id10283` are explicitly not mapped |
| [Health History Neonate](health-history-neonate.md) | helper-dependent | completed; helper-driven `Id10351` to `s28` path is now explicit |
| [Neonatal Baby Mother](neonatal-baby-mother.md) | cross-subcategory merge | completed; exact one-hot complication merge is explicit |
| [Maternal Delivery](maternal-delivery.md) | partial | completed; visible retained subset and hidden older-source dependency are explicit |
| [Medical Certificates](medical-certs.md) | free-text branch | completed; generic free-text retention path is explicit |

## Remaining QA Position

There are no remaining explicitly partial docs from the original second-pass list.

What still remains true, by design of the current codebase, is that some KB pages document one of these current-state patterns:

1. visible WHO 2022 fields that are not wired into the current adapter
2. downstream SmartVA symptom families that still depend on older hidden source fields
3. generic free-text retention instead of named structured symptom mapping
4. helper-field dependence outside the visible subcategory

Those are no longer documentation gaps. They are part of the current implementation.

## Current-State Summary

The KB is now closed for the current tracing pass:

- configured category/subcategory coverage is complete
- uncategorized/system fields are covered
- summary matrix is generated
- previously partial docs have been deep-traced and completed

So any further work would be a new pass, not a continuation of the current one.
