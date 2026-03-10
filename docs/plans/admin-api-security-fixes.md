---
# Plan: Admin API Security Fixes

[vgz.8]

## Goal
Fix security issues in the `/admin` API routes identified during code review.

## Key changes
1. **Add explicit role-based decorator** for route access control
2. **Add input validation** for project_id and site_id
3. **Fix error message** for global-scope grant toggle
4. **Add orphaned grants API** endpoint
5. **Add tests** for Odk-related routes

## Implementation Approach

1. Create a role-based decorator system with three roles:
   - `admin`: Full admin access (all endpoints)
   - `project_pi`: Project PI level access (project-scoped endpoints)
   - `any`: No access (unauthenticated)

2. Add a `validate_entity_id()` helper function to validate project_id/site_id format
3. Modify error messages for more descriptive errors
4. Create new `/api/access-grants/orphaned` endpoint:
   - `GET /api/access-grants/orphaned` - List grants where the project_site is missing or deactivated
   - `GET /api/access-grants/orphaned/<project_id>` - List orphaned grants for a project
5. Add test file `tests/test_admin_api.py`:
   - Test ODK connections CRUD
   - Test ODK project/form listing
   - Test ODK site mappings

   - Test orphaned grants API

6. Update existing tests to needed

</plan>

## Questions to clarify
1. **Role decorator behavior** - should the allow anonymous access? Currently, `@admin.before_request` allows any authenticated user with a session to access ALL `/admin/api/*` routes. We if we allow anonymous access to the bootstrap endpoint, we can:
   - Options:
     - **Yes** - Bootstrap and panel routes should be publicly accessible
     - **No** - Everything else should require authentication
   - **Explicit roles** - Which roles should be required for each route? (e.g., `admin`, `project_pi`, `any`)
2. **Input validation format** - what characters are allowed in project_id/site_id? (Currently uppercase alphanumeric + length check only)

   - Options:
     - **Alphanumeric uppercase** - Only allow A-Z,0-9, digits, and underscores
     - **Alphanumeric uppercase with dashes** - Only allow A-Z, 0-9
     - **Alphanumeric uppercase with dashes** - Only allow a-z, 0-9
3. **Fix error message** - should this be more descriptive? (Currently: "You do not have access to that project.")
4. **Orphaned grants API**
   - Create new endpoint that returns grants where:
   - The project_site_id references a deleted or deactivated project-site mapping
   - Optionally filter by project_id
   - Return count
   - Support role filtering ( project-level access for project_pis )
5. **Add tests** for Odk routes
   - Add new test class or extend the existing test class
   - Add test methods for ODK connections CRUD, project assignment, form listing, and site mappings

   - Test the orphaned grants endpoint

</plan>
## Questions to clarify
1. **Anonymous access to bootstrap** - should the endpoint be publicly accessible?
 (Bootstrap is used to the React admin panel to get the CSRF token and user info, and as login status.)

   - **No** - It should be only accessible by admin or project_pi for these endpoints.
   - **Require any role** - The routes will return 403 Forbidden
   - **Yes** - This should require authentication
   - **Yes** - The bootstrap endpoint should be accessible by both
   - **No** - No anonymous access should be allowed.

   - **Alphanumeric** - only allow letters, digits, underscores, and hyphens. Length restrictions.
   - **Alphanumeric** - Only allow letters, digits, underscores, hyphens, and length restrictions (4 chars for site_id)
   - **Any** - No additional validation needed
3. **Fix error message**
   - Change from "You do not have access to that project." to "Cannot manage this grant" or "Permission denied."
   - Current message: "This operation is not permitted."
   - **Add orphaned grants API**
   - Create `GET /api/access-grants/orphaned` endpoint
   - Create `POST /api/access-grants/orphaned` endpoint to cleanup orphaned grants
   - **Add tests**
   - Add test file `tests/test_admin_api.py`
   - Add ODK connection tests
   - Add ODK project assignment test
   - Add ODK project/form listing test
   - Add ODK site mapping test
   - Add orphaned grants test
