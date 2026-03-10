---
title: Field Mapping System Implementation - Overview
doc_type: implementation-plan
status: draft
owner: engineering
last_updated: 2026-03-10
priority: P0
---

# Field Mapping System Implementation

## Executive Summary

Implement a database-backed field mapping system that:
1. **Preserves all existing WHO_2022_VA mappings** (427 fields, 14 categories, 1199 choices)
2. Enables multi-form-type support (BALLABGARH_VA, SMART_VA)
3. Auto-syncs choices from ODK Central
4. Allows project-specific customization

## Critical Principle

> **NO DATA LOSS**: Every existing mapping in `mapping_labels.xlsx` and `mapping_choices.xlsx`
> must be preserved and migrated to the database before any new functionality is added.

## Existing Assets to Preserve

| Asset | Location | Records | Purpose |
|-------|----------|---------|---------|
| `mapping_labels.xlsx` | `resource/mapping/` | 427 rows | Field display config for WHO_2022_VA |
| `mapping_choices.xlsx` | `resource/mapping/` | 1199 rows | Choice mappings for WHO_2022_VA |
| Generated Python modules | `app/utils/va_mapping/` | 7 files | Current runtime mapping |
| Category order list | `va_preprocess_03_categoriestodisplay.py` | 14 categories | Display order |

## Implementation Phases

| Phase | Description | Risk | Duration |
|-------|-------------|------|----------|
| [Phase 1](01-phase1-database-schema.md) | Database schema + migrations | Low | 1 day |
| [Phase 2](02-phase2-migrate-existing.md) | Migrate WHO_2022_VA data | **Critical** | 1 day |
| [Phase 3](03-phase3-verify-migration.md) | Verify migration completeness | **Critical** | 0.5 day |
| [Phase 4](04-phase4-render-integration.md) | Update render functions | Medium | 1 day |
| [Phase 5](05-phase5-odk-sync-service.md) | ODK schema sync service | Medium | 1 day |
| [Phase 6](06-phase6-new-form-types.md) | Add new form types | Low | 0.5 day |
| [Phase 7](07-phase7-admin-ui.md) | **Admin UI** (HTMX-based) | **Important** | 2 days |

## Rollout Strategy

```
┌─────────────────────────────────────────────────────────────────────┐
│ COMPREHENSIVE TESTING → CLEAN CUTOVER                               │
│                                                                      │
│  Phase 1-3: Build and Verify                                        │
│       ├── Create database schema                                    │
│       ├── Migrate WHO_2022_VA data from Excel                      │
│       └── COMPREHENSIVE VERIFICATION (100% match required)         │
│                                                                      │
│  Phase 4: Clean Cutover                                             │
│       ├── Update render functions to use database                  │
│       ├── Deprecate Excel-based code (keep for rollback)           │
│       └── Full integration testing                                  │
│                                                                      │
│  Phase 5-7: Enhancements                                            │
│       ├── ODK sync service                                          │
│       ├── New form types                                            │
│       └── Admin UI                                                  │
│                                                                      │
│  NO PARALLEL OPERATION - We test comprehensively, then cut over.    │
│  Excel files remain as backup/rollback option.                      │
└─────────────────────────────────────────────────────────────────────┘
```

### TDD Approach

Each phase follows Test-Driven Development:
1. **Write tests first** - Define expected behavior
2. **Implement** - Make tests pass
3. **Verify** - Ensure no regressions
4. **Document** - Update docs

### Verification Gates

- **Phase 2 → Phase 3**: All data migrated (427 fields, 1199 choices)
- **Phase 3 → Phase 4**: 100% verification tests pass
- **Phase 4 → Phase 5**: Render output matches old system exactly

## Success Criteria

### Must Have (Phase 1-4)
- [ ] All 427 field mappings migrated to database
- [ ] All 1199 choice mappings migrated to database
- [ ] All 14 categories with correct display order
- [ ] Render output matches current system exactly
- [ ] Zero data loss from existing Excel files

### Should Have (Phase 5-6)
- [ ] ODK schema auto-sync working
- [ ] New form type (BALLABGARH_VA) configurable
- [ ] Project-specific customization possible

### Important (Phase 7) - Admin UI
- [ ] HTMX-based, responsive admin interface
- [ ] Form type management
- [ ] Category/field configuration
- [ ] Choice mapping management
- [ ] ODK sync trigger
- [ ] PII field marking
- [ ] Visual diff when ODK schema changes

## Rollback Plan

Each phase includes a rollback procedure:

| Phase | Rollback |
|-------|----------|
| 1 | Drop new tables (no data affected) |
| 2 | Delete migrated data, continue with Excel |
| 3 | N/A (verification only) |
| 4 | Revert code, continue with Excel |
| 5+ | Feature not used until verified |

## File Index

```
docs/planning/field-mapping-implementation/
├── 00-overview.md                    ← This file
├── 01-phase1-database-schema.md     ← Database schema creation
├── 02-phase2-migrate-existing.md    ← Migrate WHO_2022_VA data
├── 03-phase3-verify-migration.md    ← Verification procedures
├── 04-phase4-render-integration.md  ← Update render functions
├── 05-phase5-odk-sync-service.md    ← ODK schema sync
├── 06-phase6-new-form-types.md      ← Add new form types
└── 07-phase7-admin-ui.md            ← Admin UI (future)
```

## Related Documentation

- [Field Mapping System - Current State](../../current-state/field-mapping-system.md)
- [ODK Sync](../../current-state/odk-sync.md)
- [Data Model](../../current-state/data-model.md)
