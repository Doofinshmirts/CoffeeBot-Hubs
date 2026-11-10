# CoffeeBot Hubs

A mobile-first student prototype connecting coffee-ground drop-offs to community collection hubs. Drivers record deposits; registered individuals and organizations record how many kilograms they collect. Both journeys include a clearly labelled simulation of choosing a hub, opening its locked lid, activating its scale, photographing the final reading, and locking it again.

## Current delivery status

See [docs/VERIFICATION.md](docs/VERIFICATION.md) for checks actually run and remaining deployment dependencies. A source package is not evidence that the public deployment is complete.

## Local setup on Windows

From this folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe scripts/setup_local.py
.\.venv\Scripts\python.exe scripts/fetch_fonts.py
.\.venv\Scripts\python.exe app.py
```

Open http://127.0.0.1:5000. `setup_local.py` privately prompts for a Supabase server secret, the public publishable key, and your chosen staff password, then writes the ignored `.env`. The legacy staff username is `driver`. Find the keys in your project's Supabase Settings > API Keys. Never paste the server secret into source files or the submission.

On macOS/Linux, use `.venv/bin/python` instead. The production command is `gunicorn --workers 1 --threads 4 --timeout 60 app:app`. The local Windows command uses Waitress. No debugger is enabled.

## Supabase

Project: CoffeeBot Hubs. Reference: `mbpvfilblwuayldznsev`. Region: Singapore. Organization: malbukha Org. Project creation was quoted at $0/month.

For a fresh project, apply `sql/schema.sql` once, then `sql/seed.sql`, then every file in `sql/migrations/` in filename order. The schema, seed, and `20261110_account_hub_access.sql` migration are already applied to the project above; do not rerun them there. All three locations are fictional demonstrations, not real operating collection points.

The browser never receives the server secret. Flask uses it for server-only database, RPC, and private `dropoff-evidence` access; a separate publishable key is used only for Supabase Auth. New accounts are always created as community users. Driver promotion requires the private `scripts/create_driver.py` admin helper. Tables have RLS enabled and no direct anonymous/authenticated Data API access. This intentionally produces the informational advisor notice "RLS enabled, no policy": the service role is the only permitted application caller.

Photos are validated, resized to at most 1600 x 1600, re-encoded as JPEG and stripped of metadata. The server proxies photos only for signed-in staff; there are no public evidence URLs. Weights are positive, at most 10 kg to match the proposed scale, and have at most two decimal places.

## Mobile workflow

1. Anyone can browse hubs and availability. Registration is available for an individual or organization and requires contact details plus email confirmation.
2. A signed-in driver chooses a hub and presses **Open lid**. The interface explicitly simulates unlocking the cardboard hub and activating its scale for five minutes.
3. The driver enters the source, deposited weight, and a photo. A successful save atomically raises the hub inventory, closes the session, locks the simulated lid, and stops the simulated scale.
4. A signed-in community user chooses a hub with available grounds and opens it. The screen shows the starting weight.
5. The user removes grounds, enters the remaining scale weight, and attaches a photo. The database calculates kilograms taken as `starting weight - remaining weight`, lowers inventory atomically, and closes the session.
6. The public page checks every 10 seconds while visible and reflects the new availability. Only one open session is allowed per hub, and expired sessions cannot change inventory.

Alerts work only while the webpage is open. The lock, lid, and scale are software simulations for the cardboard prototype: there is no electrical connection to hardware. There is no OS push, reservation, OCR, or route optimisation. Camera chooser behaviour varies by device; use a JPEG/PNG/WebP upload if direct capture is unavailable. HEIC must be converted before upload.

## MVC layout

`coffeebot/models.py` owns database operations and totals. `controllers.py` owns routes, login, validation orchestration and workflows. `templates/` contains reusable Jinja screens. `services.py` handles weight and image processing. `static/app.js` handles photo preview, location sorting and polling.

Public routes include `/`, `/hubs/<id>`, `/api/availability`, `/health`, `/account/register`, and `/account/login`. Authenticated hub sessions use `/hubs/<id>/access` and `/hub-sessions/<id>`. The legacy driver login remains at `/staff/login`; evidence remains server-proxied and staff-only.

## Render deployment

1. Put this folder's contents at the root of a dedicated Git repository and push it to an account you control.
2. In Render, create a Blueprint from the repository using `render.yaml`, or create a Python Web Service manually using the same commands.
3. Select the **Free** instance. Set the Supabase server secret and staff password hash in Render's private environment settings. Generate a hash with `python scripts/password_hash.py`. The Blueprint supplies the public publishable key and public app URL. Keep `COOKIE_SECURE=true`; Render generates the session secret through the Blueprint.
4. Build: `pip install -r requirements.txt`. Start: `gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT app:app`.
5. In Supabase Authentication > URL Configuration, set the Site URL to `https://coffeebot-hubs.onrender.com` and allow `https://coffeebot-hubs.onrender.com/account/login` as a redirect URL.
6. Open the assigned HTTPS URL, check `/health`, then test the full workflow in independent driver and community browser sessions. `/health` confirms the process, not database connectivity; load the hub page too.

Render Free may take around a minute to wake after 15 minutes without traffic. Open and test the app before presenting. All data persists in Supabase rather than Render's ephemeral filesystem. A local run still needs Supabase connectivity; use a recorded verified demo if the internet fails entirely.

## Tests and recording

```powershell
.\.venv\Scripts\python.exe -m pytest -q
# Separate terminal for browser fixtures (synthetic in-memory data only):
.\.venv\Scripts\python.exe -m tests.preview_server
# Requires Microsoft Edge, or adapt launch() to an installed Playwright browser:
.\.venv\Scripts\python.exe -m tests.browser_check
```

Browser QA uses synthetic fixtures on port 5055, not Supabase. Its recording must be labeled a fixture walkthrough. Record a separate real Supabase demonstration after live verification, following `docs/DEMO_SCRIPT.md`.

After a successful installation, record resolved versions with `python -m pip freeze` into `requirements-lock.txt`. Direct runtime requirements are pinned; a fully resolved lock is not supplied until dependency installation succeeds.

## Submission

Run `python scripts/package_submission.py` to create `CoffeeBot_Hubs_Source.zip` in the parent folder. Its allowlist excludes `.env`, virtual environments and artifacts. Include the separately verified demo recording and public URL once deployed. Keep screenshots and videos free of passwords and secrets.

## Limits

This is a supervised student demo, not a production access-control system. The shared legacy staff identity has no per-driver audit identity; create named drivers later if needed. Login throttling is process-local, with ten attempts per five minutes; use one worker. A restart resets the throttle. A rare ambiguous database timeout preserves an uploaded photo rather than risking deletion of referenced evidence; staff may need to remove orphaned files later. Inventory means recorded scale entries, not verified reuse or carbon avoided. The physical lock, scale, cleanliness checks, and collection remain supervised and are not electronically controlled by this code.
