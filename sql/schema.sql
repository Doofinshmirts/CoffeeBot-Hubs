-- Run once in a fresh Supabase project. All application access is server mediated.
create table public.hubs (
  id bigint generated always as identity primary key,
  name text not null unique,
  address text not null,
  latitude double precision not null check (latitude between -90 and 90),
  longitude double precision not null check (longitude between -180 and 180),
  instructions text not null,
  active boolean not null default true,
  is_demo boolean not null default true
);
create table public.dropoffs (
  id uuid primary key,
  submission_id uuid not null unique,
  hub_id bigint not null references public.hubs(id),
  rider_source text not null check (length(rider_source) between 1 and 80),
  weight_kg numeric(5,2) not null check (weight_kg > 0 and weight_kg <= 10),
  created_at timestamptz not null default now(),
  photo_path text not null unique,
  status text not null default 'available' check (status in ('available', 'collected')),
  collected_at timestamptz,
  check ((status = 'available' and collected_at is null) or (status = 'collected' and collected_at is not null))
);
create index dropoffs_hub_status_idx on public.dropoffs(hub_id, status);
create index dropoffs_created_at_idx on public.dropoffs(created_at desc);
alter table public.hubs enable row level security;
alter table public.dropoffs enable row level security;
revoke all on public.hubs, public.dropoffs from anon, authenticated;
grant all on public.hubs, public.dropoffs to service_role;
grant usage, select on sequence public.hubs_id_seq to service_role;

insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('dropoff-evidence', 'dropoff-evidence', false, 10485760, array['image/jpeg'])
on conflict (id) do nothing;
-- No anonymous/authenticated storage policies: only the server secret may access evidence.
