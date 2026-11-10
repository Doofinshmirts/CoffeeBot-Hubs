-- Add authenticated community accounts, simulated hub access, and partial collections.
-- This migration is additive and preserves all existing hubs, drop-offs, and evidence.

alter table public.hubs
  add column if not exists current_weight_kg numeric(6,2) not null default 0;

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'hubs_current_weight_kg_check'
      and conrelid = 'public.hubs'::regclass
  ) then
    alter table public.hubs add constraint hubs_current_weight_kg_check
      check (current_weight_kg >= 0 and current_weight_kg <= 999.99);
  end if;
end $$;

update public.hubs h
set current_weight_kg = coalesce((
  select sum(d.weight_kg)
  from public.dropoffs d
  where d.hub_id = h.id and d.status = 'available'
), 0);

create table if not exists public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text not null unique check (length(email) between 3 and 320),
  role text not null default 'community' check (role in ('community', 'driver')),
  account_type text not null check (account_type in ('individual', 'organization')),
  full_name text not null check (length(full_name) between 2 and 100),
  phone text not null check (length(phone) between 6 and 30),
  organization_name text,
  organization_type text,
  active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (
    (account_type = 'individual' and organization_name is null and organization_type is null)
    or
    (account_type = 'organization'
      and length(organization_name) between 2 and 120
      and organization_type in ('school', 'company', 'nonprofit', 'community_group', 'other'))
  )
);

create table if not exists public.hub_access_sessions (
  id uuid primary key,
  hub_id bigint not null references public.hubs(id),
  profile_id uuid references public.profiles(id) on delete restrict,
  legacy_driver boolean not null default false,
  action text not null check (action in ('dropoff', 'collection')),
  status text not null default 'open' check (status in ('open', 'completed', 'cancelled', 'expired')),
  opening_weight_kg numeric(6,2) not null check (opening_weight_kg >= 0),
  opened_at timestamptz not null default now(),
  expires_at timestamptz not null,
  closed_at timestamptz,
  check ((profile_id is not null and not legacy_driver) or (profile_id is null and legacy_driver)),
  check ((status = 'open' and closed_at is null) or (status <> 'open' and closed_at is not null))
);

create table if not exists public.collections (
  id uuid primary key,
  session_id uuid not null unique references public.hub_access_sessions(id) on delete restrict,
  hub_id bigint not null references public.hubs(id),
  profile_id uuid not null references public.profiles(id) on delete restrict,
  weight_before_kg numeric(6,2) not null check (weight_before_kg > 0),
  weight_after_kg numeric(6,2) not null check (weight_after_kg >= 0),
  collected_kg numeric(6,2) generated always as (weight_before_kg - weight_after_kg) stored,
  photo_path text not null unique,
  created_at timestamptz not null default now(),
  check (weight_after_kg < weight_before_kg)
);

alter table public.dropoffs add column if not exists profile_id uuid references public.profiles(id) on delete restrict;
alter table public.dropoffs add column if not exists session_id uuid unique references public.hub_access_sessions(id) on delete restrict;
alter table public.dropoffs add column if not exists legacy_driver boolean not null default false;

create index if not exists profiles_active_idx on public.profiles(id) where active;
create index if not exists hub_access_sessions_profile_idx on public.hub_access_sessions(profile_id, opened_at desc);
create index if not exists hub_access_sessions_hub_idx on public.hub_access_sessions(hub_id, opened_at desc);
create unique index if not exists hub_access_sessions_one_open_per_hub_idx
  on public.hub_access_sessions(hub_id) where status = 'open';
create index if not exists collections_profile_idx on public.collections(profile_id, created_at desc);
create index if not exists collections_hub_idx on public.collections(hub_id, created_at desc);
create index if not exists dropoffs_profile_idx on public.dropoffs(profile_id) where profile_id is not null;
create index if not exists dropoffs_session_idx on public.dropoffs(session_id) where session_id is not null;

alter table public.profiles enable row level security;
alter table public.hub_access_sessions enable row level security;
alter table public.collections enable row level security;

revoke all on public.profiles, public.hub_access_sessions, public.collections from anon, authenticated;
grant select, insert, update on public.profiles, public.hub_access_sessions, public.collections to service_role;
grant select, insert, update on public.hubs, public.dropoffs to service_role;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

create or replace function private.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_account_type text;
begin
  v_account_type := case
    when new.raw_user_meta_data ->> 'account_type' = 'organization' then 'organization'
    else 'individual'
  end;

  insert into public.profiles (
    id, email, role, account_type, full_name, phone, organization_name, organization_type
  ) values (
    new.id,
    lower(new.email),
    'community',
    v_account_type,
    trim(coalesce(new.raw_user_meta_data ->> 'full_name', '')),
    trim(coalesce(new.raw_user_meta_data ->> 'phone', '')),
    case when v_account_type = 'organization' then trim(new.raw_user_meta_data ->> 'organization_name') end,
    case when v_account_type = 'organization' then new.raw_user_meta_data ->> 'organization_type' end
  );
  return new;
end;
$$;

revoke all on function private.handle_new_auth_user() from public, anon, authenticated;
grant execute on function private.handle_new_auth_user() to supabase_auth_admin;

do $$
begin
  if not exists (select 1 from pg_trigger where tgname = 'on_auth_user_created') then
    create trigger on_auth_user_created
      after insert on auth.users
      for each row execute function private.handle_new_auth_user();
  end if;
end $$;

create or replace function public.open_hub_session(
  p_session_id uuid,
  p_hub_id bigint,
  p_profile_id uuid,
  p_legacy_driver boolean,
  p_action text
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_weight numeric(6,2);
  v_role text;
  v_active boolean;
begin
  update hub_access_sessions
  set status = 'expired', closed_at = now()
  where status = 'open' and expires_at <= now();

  select current_weight_kg into v_weight
  from hubs where id = p_hub_id and active
  for update;
  if not found then raise exception 'hub_not_found'; end if;

  if p_legacy_driver then
    if p_profile_id is not null or p_action <> 'dropoff' then
      raise exception 'role_not_allowed';
    end if;
  else
    select role, active into v_role, v_active from profiles where id = p_profile_id;
    if not found or not v_active then raise exception 'account_inactive'; end if;
    if (v_role = 'driver' and p_action <> 'dropoff')
       or (v_role = 'community' and p_action <> 'collection') then
      raise exception 'role_not_allowed';
    end if;
    if p_action = 'collection' and v_weight <= 0 then raise exception 'nothing_available'; end if;
  end if;

  insert into hub_access_sessions (
    id, hub_id, profile_id, legacy_driver, action, opening_weight_kg, expires_at
  ) values (
    p_session_id, p_hub_id, p_profile_id, p_legacy_driver, p_action, v_weight, now() + interval '5 minutes'
  );

  return jsonb_build_object('id', p_session_id, 'opening_weight_kg', v_weight, 'action', p_action);
exception
  when unique_violation then raise exception 'hub_in_use';
end;
$$;

create or replace function public.complete_hub_dropoff(
  p_session_id uuid,
  p_profile_id uuid,
  p_legacy_driver boolean,
  p_dropoff_id uuid,
  p_source text,
  p_weight_kg numeric,
  p_photo_path text
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_session hub_access_sessions%rowtype;
  v_current numeric(6,2);
begin
  if exists (select 1 from dropoffs where session_id = p_session_id) then
    select current_weight_kg into v_current from hubs
    where id = (select hub_id from hub_access_sessions where id = p_session_id);
    return jsonb_build_object('dropoff_id', p_dropoff_id, 'current_weight_kg', v_current, 'replayed', true);
  end if;

  select * into v_session from hub_access_sessions where id = p_session_id for update;
  if not found or v_session.action <> 'dropoff' then raise exception 'invalid_session'; end if;
  if v_session.status <> 'open' then raise exception 'session_closed'; end if;
  if v_session.expires_at <= now() then
    update hub_access_sessions set status = 'expired', closed_at = now() where id = p_session_id;
    return jsonb_build_object('error', 'session_expired');
  end if;
  if v_session.profile_id is distinct from p_profile_id
     or v_session.legacy_driver is distinct from p_legacy_driver then
    raise exception 'session_not_owned';
  end if;
  if p_weight_kg <= 0 or p_weight_kg > 10 then raise exception 'invalid_weight'; end if;

  select current_weight_kg into v_current from hubs where id = v_session.hub_id for update;
  insert into dropoffs (
    id, submission_id, hub_id, rider_source, weight_kg, photo_path,
    profile_id, session_id, legacy_driver
  ) values (
    p_dropoff_id, p_dropoff_id, v_session.hub_id, p_source, p_weight_kg, p_photo_path,
    p_profile_id, p_session_id, p_legacy_driver
  );
  update hubs set current_weight_kg = current_weight_kg + p_weight_kg where id = v_session.hub_id
    returning current_weight_kg into v_current;
  update hub_access_sessions set status = 'completed', closed_at = now() where id = p_session_id;
  return jsonb_build_object('dropoff_id', p_dropoff_id, 'current_weight_kg', v_current, 'replayed', false);
end;
$$;

create or replace function public.complete_hub_collection(
  p_session_id uuid,
  p_profile_id uuid,
  p_collection_id uuid,
  p_weight_after_kg numeric,
  p_photo_path text
)
returns jsonb
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
declare
  v_session hub_access_sessions%rowtype;
  v_before numeric(6,2);
  v_taken numeric(6,2);
begin
  if exists (select 1 from collections where session_id = p_session_id) then
    select weight_before_kg, collected_kg into v_before, v_taken from collections where session_id = p_session_id;
    return jsonb_build_object('collection_id', p_collection_id, 'current_weight_kg', v_before - v_taken,
                              'collected_kg', v_taken, 'replayed', true);
  end if;

  select * into v_session from hub_access_sessions where id = p_session_id for update;
  if not found or v_session.action <> 'collection' then raise exception 'invalid_session'; end if;
  if v_session.status <> 'open' then raise exception 'session_closed'; end if;
  if v_session.expires_at <= now() then
    update hub_access_sessions set status = 'expired', closed_at = now() where id = p_session_id;
    return jsonb_build_object('error', 'session_expired');
  end if;
  if v_session.profile_id is distinct from p_profile_id then raise exception 'session_not_owned'; end if;

  select current_weight_kg into v_before from hubs where id = v_session.hub_id for update;
  if p_weight_after_kg < 0 or p_weight_after_kg >= v_before then raise exception 'invalid_remaining_weight'; end if;
  v_taken := v_before - p_weight_after_kg;

  insert into collections (
    id, session_id, hub_id, profile_id, weight_before_kg, weight_after_kg, photo_path
  ) values (
    p_collection_id, p_session_id, v_session.hub_id, p_profile_id, v_before, p_weight_after_kg, p_photo_path
  );
  update hubs set current_weight_kg = p_weight_after_kg where id = v_session.hub_id;
  update hub_access_sessions set status = 'completed', closed_at = now() where id = p_session_id;
  return jsonb_build_object('collection_id', p_collection_id, 'current_weight_kg', p_weight_after_kg,
                            'collected_kg', v_taken, 'replayed', false);
end;
$$;

create or replace function public.cancel_hub_session(
  p_session_id uuid,
  p_profile_id uuid,
  p_legacy_driver boolean
)
returns boolean
language plpgsql
security invoker
set search_path = public, pg_temp
as $$
begin
  update hub_access_sessions
  set status = 'cancelled', closed_at = now()
  where id = p_session_id and status = 'open'
    and profile_id is not distinct from p_profile_id
    and legacy_driver is not distinct from p_legacy_driver;
  return found;
end;
$$;

revoke all on function public.open_hub_session(uuid,bigint,uuid,boolean,text) from public, anon, authenticated;
revoke all on function public.complete_hub_dropoff(uuid,uuid,boolean,uuid,text,numeric,text) from public, anon, authenticated;
revoke all on function public.complete_hub_collection(uuid,uuid,uuid,numeric,text) from public, anon, authenticated;
revoke all on function public.cancel_hub_session(uuid,uuid,boolean) from public, anon, authenticated;
grant execute on function public.open_hub_session(uuid,bigint,uuid,boolean,text) to service_role;
grant execute on function public.complete_hub_dropoff(uuid,uuid,boolean,uuid,text,numeric,text) to service_role;
grant execute on function public.complete_hub_collection(uuid,uuid,uuid,numeric,text) to service_role;
grant execute on function public.cancel_hub_session(uuid,uuid,boolean) to service_role;
