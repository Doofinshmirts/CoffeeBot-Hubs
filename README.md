# CoffeeBot Hubs

A mobile-first student prototype connecting coffee-ground drop-offs to community collection hubs. Drivers record a net scale reading and photograph; community visitors see available kilograms and live webpage alerts; staff mark full batches collected.

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

Open http://127.0.0.1:5000. `setup_local.py` privately prompts for a Supabase server secret and your chosen staff password, then writes the ignored `.env`. The staff username is `driver`. Find the secret in your project's Supabase Settings > API Keys. Never paste secrets into source files or the submission.

On macOS/Linux, use `.venv/bin/python` instead. The production command is `gunicorn --workers 1 --threads 4 --timeout 60 app:app`. The local Windows command uses Waitress. No debugger is enabled.

## Supabase

Project: CoffeeBot Hubs. Reference: `mbpvfilblwuayldznsev`. Region: Singapore. Organization: malbukha Org. Project creation was quoted at $0/month.

For a fresh project, apply `sql/schema.sql` once, followed by `sql/seed.sql`. The schema was already applied to the project above; do not rerun it there. The seed is safe to repeat because hub names are unique. All three locations are fictional demonstrations, not real operating collection points.

The Flask server uses the secret key to access the database and private `dropoff-evidence` bucket. Tables have RLS enabled and no anonymous/authenticated access. This intentionally produces the informational advisor notice "RLS enabled, no policy": the service role is the only permitted application caller.

Photos are validated, resized to at most 1600 x 1600, re-encoded as JPEG and stripped of metadata. The server proxies photos only for signed-in staff; there are no public evidence URLs. Weights are positive, at most 10 kg to match the proposed scale, and have at most two decimal places.

## Mobile workflow

1. Community users open the home page. No account is required.
2. Optionally choose **Use my location**. Sorting uses straight-line distance; coordinates stay in the browser. Browsing works when location is denied.
3. Staff sign in, choose a hub, enter a rider/source, tare the container, enter net kilograms and attach a photo showing grounds and the scale reading.
4. Submit. The confirmation appears only after the record is saved.
5. The community page checks every 10 seconds while visible and alerts once for each newly observed batch. Existing batches on page load do not trigger alerts.
6. After the entire batch is collected, staff mark it collected. Available kilograms decrease on the next community refresh.

Alerts work only while the webpage is open. There is no OS push, email, reservation, partial collection, OCR, automatic scale connection or route optimisation in this version. Camera chooser behaviour varies by device; use a JPEG/PNG/WebP upload if direct capture is unavailable. HEIC must be converted before upload.

## MVC layout

`coffeebot/models.py` owns database operations and totals. `controllers.py` owns routes, login, validation orchestration and workflows. `templates/` contains reusable Jinja screens. `services.py` handles weight and image processing. `static/app.js` handles photo preview, location sorting and polling.

Public routes: `/`, `/hubs/<id>`, `/api/availability`, `/health`. Staff routes: `/staff/login`, `/staff/logout`, `/staff/dropoffs/new`, confirmation, batch management, collection and authenticated evidence-photo access.

## Render deployment

1. Put this folder's contents at the root of a dedicated Git repository and push it to an account you control.
2. In Render, create a Blueprint from the repository using `render.yaml`, or create a Python Web Service manually using the same commands.
3. Select the **Free** instance. Set the Supabase secret and staff password hash in Render's private environment settings. Generate a hash with `python scripts/password_hash.py`. Keep `COOKIE_SECURE=true`; Render generates the session secret through the Blueprint.
4. Build: `pip install -r requirements.txt`. Start: `gunicorn --workers 1 --threads 4 --timeout 60 --bind 0.0.0.0:$PORT app:app`.
5. Open the assigned HTTPS URL, check `/health`, then test the full workflow on two devices. `/health` confirms the process, not database connectivity; load the hub page too.

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

This is a supervised student demo, not a production service. A shared staff identity has no per-driver permissions. Login throttling is process-local, with ten attempts per five minutes across the demonstration account; use one worker. A process restart resets the throttle. A rare ambiguous database timeout preserves an uploaded photo rather than risking deletion of referenced evidence; staff may need to remove orphaned files later. Inventory means recorded available grounds, not verified reuse or carbon avoided. The physical scale, cleanliness checks and actual collection remain supervised tasks.
