-- Persist the locked state when a completion is attempted after session expiry.
-- Returning a structured error avoids rolling back the status update.

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

revoke all on function public.complete_hub_dropoff(uuid,uuid,boolean,uuid,text,numeric,text)
  from public, anon, authenticated;
revoke all on function public.complete_hub_collection(uuid,uuid,uuid,numeric,text)
  from public, anon, authenticated;
grant execute on function public.complete_hub_dropoff(uuid,uuid,boolean,uuid,text,numeric,text)
  to service_role;
grant execute on function public.complete_hub_collection(uuid,uuid,uuid,numeric,text)
  to service_role;
