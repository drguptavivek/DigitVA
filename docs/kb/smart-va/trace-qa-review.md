---
title: SmartVA Trace QA Review
doc_type: kb
status: active
owner: engineering
last_updated: 2026-04-15
---

# SmartVA Trace QA Review

This document is the second-pass QA review after the initial `WHO_2022_VA_SOCIAL` tracing pass.

Its purpose is not to reopen every documented block. It identifies the KB pages where the current trace is explicitly partial, dependent on helper fields outside the visible block, or less explicit in the WHO adapter than in the downstream symptom/tariff layers.

Related docs:

- [WHO_2022_VA_SOCIAL Category / Subcategory Inventory](who-2022-va-social-subcategory-inventory.md)
- [Uncategorized And System Fields](uncategorized-system-fields.md)
- [SmartVA Agentic Tracing Instructions](agentic-tracing-instructions.md)

## QA Findings

| KB doc | QA status | Why it still deserves a deeper pass |
|---|---|---|
| [Duration Of Illness](duration-of-illness.md) | partial | adult downstream duration path is clear, but the WHO-side builder for the adult duration variable is less explicit than the child/neonate helper path |
| [Chest Pain](chest-pain.md) | partial | `Id10174` is clearly wired, but the visible WHO follow-up subfields are not all explicitly surfaced in the current adapter tables |
| [Headache](headache.md) | partial | downstream symptom family is clear, but the exact WHO-side adapter wiring is less explicit than for simpler families |
| [Mental Confusion](mental-confusion.md) | partial | downstream family is explicit, but the visible WHO-side mapping for `Id10212` and `Id10213*` is not fully explicit |
| [Stiff Neck](stiff-neck.md) | partial | downstream family is explicit, but the exact WHO 2022 duration-field adapter path is less explicit |
| [Swelling](swelling.md) | partial | face/body puffiness is clear, but the leg/feet swelling block is less explicit in the current adapter |
| [Neonatal Delivery](neonatal-delivery.md) | partial | several visible WHO delivery fields likely feed downstream features, but the visible adapter lines are not all explicit in this fork |
| [Neonatal Unresponsive](neonatal-unresponsive.md) | partial | `s94` is clear downstream, but the exact treatment of `Id10282` and `Id10283` timing split is still not fully explicit |
| [Health History Neonate](health-history-neonate.md) | helper-dependent | the displayed subcategory depends on helper fields outside the visible block for the final duration bucket |
| [Neonatal Baby Mother](neonatal-baby-mother.md) | cross-subcategory merge | the retained complication family is real, but it merges fields from the separate delivery subcategory |
| [Maternal Delivery](maternal-delivery.md) | partial | visible WHO 2022 delivery fields are only partly retained; some downstream maternal-delivery symptoms still depend on older hidden fields |
| [Medical Certificates](medical-certs.md) | free-text branch | certificate cause-text fields are retained through generic free-text handling rather than direct structured symptom mapping |

## Sufficiently Closed Docs

The following types of docs look sufficiently closed for current-state purposes and do not need immediate deeper tracing unless requirements change:

- direct retained families with explicit WHO-to-symptom paths such as [Fever](fever.md), [Cough](cough.md), [Diarrhea](diarrhea.md), [Jaundice](jaundice.md), and [Neonatal Feeding](neonatal-feeding.md)
- intentionally metadata-only or ignored blocks such as [Death Registration](death-registration.md), [Medical Documents](medical-documents.md), [Death Documents](death-documents.md), [Interviewer Final Comment](iv-final.md), and [Social Autopsy](social-autopsy.md)
- blocks that are documented as mostly ignored in the current adapter and do not show evidence of hidden retained paths, such as [Smell Or Taste](smell-taste.md) and [Health Service Treatment](health-service-treatment.md)

## Current-State Summary

The KB now covers the full configured form, but the QA pass shows three recurring patterns:

1. helper-field dependency outside the visible subcategory
2. visible WHO 2022 fields feeding older PHMRC-style downstream structures only partly or indirectly
3. free-text retention paths where a displayed field does not map to a named symptom directly

So the KB is operationally complete, but not every doc is equally final.

## Code Map

- [SmartVA Agentic Tracing Instructions](agentic-tracing-instructions.md)
- [Uncategorized And System Fields](uncategorized-system-fields.md)
