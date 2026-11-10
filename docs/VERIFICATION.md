# Verification and handoff status

Checked on 10 November 2026.

## Implemented

- Public individual and organization registration with contact details and email confirmation through Supabase Auth.
- Server-controlled profiles; public registration always creates a community role and cannot self-assign driver permissions.
- Preserved legacy driver login plus a private helper for creating named driver accounts later.
- Authenticated, hub-specific access sessions with a five-minute simulated lid/scale window and one open session per hub.
- Driver deposits with source, weight, private photo, and atomic inventory increase.
- Community collections with starting weight, required remaining weight/photo, database-calculated kilograms taken, and atomic inventory decrease.
- Private evidence storage, mobile screens, session countdown, public availability polling, Render configuration, and updated demo instructions.

## Verified against live Supabase

- Additive migrations `20261110_account_hub_access.sql` and `20261110_fix_access_expiry.sql` applied successfully to project `mbpvfilblwuayldznsev`.
- Existing data was preserved: 3 hubs, 4 drop-offs, and 6.50 kg of inventory before any new demo activity.
- New `profiles`, `hub_access_sessions`, and `collections` tables have RLS enabled.
- Anonymous/authenticated Data API privileges are revoked; application RPC functions are executable only by the service role.
- The auth-user trigger creates a community profile and hardcodes the role rather than trusting registration metadata.
- Security advisor reports only the expected informational no-policy notices for server-only tables. No destructive migration or data deletion was performed.

## Automated checks completed

- Python compilation: passed.
- Flask workflow suite: **38 passed**, including external-login redirect and expired-session regressions.
- Headless mobile browser workflow: passed for registration, organization fields, simulated lid/scale access, driver deposit, community collection, responsive layout, and availability updates.
- `git diff --check`: passed.
- Browser tests use synthetic in-memory fixtures and do not claim live hardware integration.

## Required after merge

1. Allow `https://coffeebot-hubs.onrender.com/account/login` in Supabase Authentication > URL Configuration and set the Site URL to the deployed origin.
2. Let Render deploy `main`, then confirm `/health` returns `{"status":"ok"}` and load the hub list to confirm database connectivity.
3. Register a real presentation account, confirm its email, and rehearse the driver-to-community journey in two independent browser sessions.
4. Keep the cardboard lid and scale language honest: the UI simulates their controls; no real lock or scale is connected.
5. Record a backup walkthrough after the live rehearsal. Never show passwords, contact details, API secrets, or the Render environment screen.

Public deployment URL: https://coffeebot-hubs.onrender.com
