# Verification and handoff status

Checked on 5 November 2026.

## Implemented

- Python MVC source, seven rendered templates (including error screen), responsive styles and browser interactions.
- Driver login, CSRF protection, shared-account login throttling, drop-off validation, private image handling, duplicate submission protection, collection and public availability API.
- Supabase repository adapter, schema, demonstration seed script, Render Blueprint, local configuration helper, font download helper and source packaging helper.
- Automated Flask workflow tests and browser workflow checks, ready to run after dependencies are installed.

## Verified with the live Supabase connection

- CoffeeBot Hubs project created: `mbpvfilblwuayldznsev`, Singapore region, approved $0/month quote.
- `hubs` and `dropoffs` tables exist with RLS enabled.
- The anonymous role has neither SELECT nor INSERT privileges on either table.
- `dropoff-evidence` bucket is private, with a 10 MB limit.
- Security advisor returned informational RLS-without-policy notices only. This is intentional for server-only access: https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy
- Live hub count is zero. The seed tool call was cancelled and was not retried. Apply `sql/seed.sql` when ready.

## Checks actually run locally

- Python compilation for application and tests: passed.
- JavaScript syntax check: passed.
- All seven Jinja templates rendered using synthetic offline review data: passed.
- Offline image/weight checks: eight invalid weights rejected; 5 kg accepted; image resized to <=1600px; metadata absent; invalid and oversized files rejected.
- Headless Edge rendered all seven pages at 390px, and the home page at 360, 390, 768 and 1280px without horizontal overflow.
- Home, drop-off and desktop screenshots visually inspected. Uses system-font fallbacks until font assets are downloaded.

The initial offline checks used cached Jinja 3.1.5 and runtime Pillow 13.0.0. After the user installed the pinned dependencies, the Flask pytest suite ran successfully: **14 passed**. An incorrect CSRF timeout value type was found and corrected to integer seconds. These tests use an in-memory repository and do not certify the live Supabase integration. The full browser workflow suite still awaits execution.

## Remaining before calling the prototype live

1. Dependency installation completed; Flask workflow tests pass.
2. Save the Supabase server secret and staff password using `python scripts/setup_local.py` (private local prompts).
3. Apply `sql/seed.sql` to add the three explicitly fictional hubs.
4. Run `python scripts/fetch_fonts.py` to bundle Inter and Fraunces plus licenses. Until then, system fonts render the interface.
5. Run `python -m pytest -q`, then the fixture browser checks and the actual Supabase two-session workflow.
6. Resolve GitHub authorization and connect Render. Create the repository, deploy the Free service and record the public URL here.
7. Record the verified live walkthrough and do the physical phone-and-scale rehearsal.

Public deployment URL: pending deployment.
Verified live workflow recording: pending live integration.

No claim is made that the fixture screenshots or source ZIP demonstrate a live cloud-connected workflow.
