"""Database access is restricted to this module; no credentials enter templates."""
from datetime import datetime, timezone
from decimal import Decimal
from supabase import create_client


class BackendUnavailable(Exception):
    pass


class HubAccessError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def summarize(hubs, batches, collections=None):
    collections = collections or []
    result = []
    for hub in hubs:
        rows = [b for b in batches if b['hub_id'] == hub['id']]
        available = [b for b in rows if b['status'] == 'available']
        collection_rows = [c for c in collections if c['hub_id'] == hub['id']]
        available_kg = hub.get('current_weight_kg')
        if available_kg is None:
            available_kg = sum((Decimal(str(b['weight_kg'])) for b in available), Decimal('0'))
        result.append({**hub,
            'available_kg': float(available_kg),
            'deposit_count': len(rows),
            'last_update': max(
                [b['created_at'] for b in rows] + [c['created_at'] for c in collection_rows],
                default=None,
            )})
    return result


class SupabaseRepository:
    def __init__(self, url, key):
        if not url or not key:
            raise RuntimeError('Set SUPABASE_URL and SUPABASE_SECRET_KEY in .env. See README.')
        self.client = create_client(url, key)

    def _rows(self, table, columns='*'):
        # Paginate rather than silently truncating at Supabase's default row limit.
        output, start = [], 0
        while True:
            page = self.client.table(table).select(columns).order('id').range(start, start + 499).execute().data
            output.extend(page)
            if len(page) < 500:
                return output
            start += 500

    def snapshot(self):
        try:
            hubs = [h for h in self._rows('hubs') if h['active']]
            batches = self._rows('dropoffs', 'id,hub_id,weight_kg,created_at,status,collected_at')
            collections = self._rows('collections', 'id,hub_id,collected_kg,created_at')
            active_ids = {h['id'] for h in hubs}
            batches = [b for b in batches if b['hub_id'] in active_ids]
            collections = [c for c in collections if c['hub_id'] in active_ids]
            return summarize(hubs, batches, collections), batches
        except Exception:
            raise BackendUnavailable() from None

    def get_hub(self, hub_id):
        try:
            rows = self.client.table('hubs').select('*').eq('id', hub_id).eq('active', True).execute().data
            return rows[0] if rows else None
        except Exception:
            raise BackendUnavailable() from None

    def get_profile(self, profile_id):
        try:
            rows = self.client.table('profiles').select('*').eq('id', profile_id).execute().data
            return rows[0] if rows else None
        except Exception:
            raise BackendUnavailable() from None

    def get_session(self, session_id):
        try:
            rows = self.client.table('hub_access_sessions').select('*').eq('id', session_id).execute().data
            return rows[0] if rows else None
        except Exception:
            raise BackendUnavailable() from None

    def open_session(self, session_id, hub_id, profile_id, legacy_driver, action):
        try:
            data = self.client.rpc('open_hub_session', {
                'p_session_id': session_id,
                'p_hub_id': hub_id,
                'p_profile_id': profile_id,
                'p_legacy_driver': legacy_driver,
                'p_action': action,
            }).execute().data
            return data
        except Exception as error:
            self._raise_access_or_backend(error)

    @staticmethod
    def _access_code(error):
        message = str(error).lower()
        for code in (
            'hub_in_use', 'hub_not_found', 'role_not_allowed', 'account_inactive',
            'nothing_available', 'invalid_session', 'session_closed', 'session_expired',
            'session_not_owned', 'invalid_weight', 'invalid_remaining_weight',
        ):
            if code in message:
                return code
        return None

    def _raise_access_or_backend(self, error):
        code = self._access_code(error)
        if code:
            raise HubAccessError(code) from None
        raise BackendUnavailable() from None

    def get_batch(self, batch_id):
        try:
            rows = self.client.table('dropoffs').select('*').eq('id', batch_id).execute().data
            return rows[0] if rows else None
        except Exception:
            raise BackendUnavailable() from None

    def create_batch(self, batch_id, hub_id, source, weight, image):
        existing = self.get_batch(batch_id)
        if existing:
            return existing
        # Unique image per attempt: concurrent requests never overwrite/delete another's photo.
        from uuid import uuid4
        path = f'{batch_id}/{uuid4()}.jpg'
        bucket = self.client.storage.from_('dropoff-evidence')
        try:
            bucket.upload(path, image, {'content-type': 'image/jpeg', 'upsert': 'false'})
        except Exception:
            raise BackendUnavailable() from None
        try:
            row = dict(id=batch_id, submission_id=batch_id, hub_id=hub_id,
                       rider_source=source, weight_kg=str(weight), photo_path=path)
            return self.client.table('dropoffs').insert(row).execute().data[0]
        except Exception:
            # A timeout might mean the insert committed. Query before deleting evidence.
            try:
                winner = self.get_batch(batch_id)
            except BackendUnavailable:
                raise BackendUnavailable() from None  # Preserve possibly referenced object.
            if not winner or winner['photo_path'] != path:
                try:
                    bucket.remove([path])
                except Exception:
                    pass  # Log no keys or file contents; document orphan cleanup limitation.
            if winner:
                return winner
            raise BackendUnavailable() from None

    def _upload_evidence(self, prefix, event_id, image):
        from uuid import uuid4
        path = f'{prefix}/{event_id}/{uuid4()}.jpg'
        try:
            self.client.storage.from_('dropoff-evidence').upload(
                path, image, {'content-type': 'image/jpeg', 'upsert': 'false'}
            )
            return path
        except Exception:
            raise BackendUnavailable() from None

    def _remove_evidence(self, path):
        try:
            self.client.storage.from_('dropoff-evidence').remove([path])
        except Exception:
            pass

    def complete_dropoff(self, session_id, profile_id, legacy_driver, dropoff_id, source, weight, image):
        existing = self.get_batch(dropoff_id)
        if existing:
            return existing
        path = self._upload_evidence('dropoffs', dropoff_id, image)
        try:
            result = self.client.rpc('complete_hub_dropoff', {
                'p_session_id': session_id,
                'p_profile_id': profile_id,
                'p_legacy_driver': legacy_driver,
                'p_dropoff_id': dropoff_id,
                'p_source': source,
                'p_weight_kg': str(weight),
                'p_photo_path': path,
            }).execute().data
            if isinstance(result, dict) and result.get('error'):
                raise HubAccessError(result['error'])
            return self.get_batch(dropoff_id)
        except Exception as error:
            try:
                winner = self.get_batch(dropoff_id)
            except BackendUnavailable:
                raise BackendUnavailable() from None
            if winner:
                if winner.get('photo_path') != path:
                    self._remove_evidence(path)
                return winner
            self._remove_evidence(path)
            self._raise_access_or_backend(error)

    def get_collection(self, collection_id):
        try:
            rows = self.client.table('collections').select('*').eq('id', collection_id).execute().data
            return rows[0] if rows else None
        except Exception:
            raise BackendUnavailable() from None

    def complete_collection(self, session_id, profile_id, collection_id, remaining_weight, image):
        existing = self.get_collection(collection_id)
        if existing:
            return existing
        path = self._upload_evidence('collections', collection_id, image)
        try:
            result = self.client.rpc('complete_hub_collection', {
                'p_session_id': session_id,
                'p_profile_id': profile_id,
                'p_collection_id': collection_id,
                'p_weight_after_kg': str(remaining_weight),
                'p_photo_path': path,
            }).execute().data
            if isinstance(result, dict) and result.get('error'):
                raise HubAccessError(result['error'])
            return self.get_collection(collection_id)
        except Exception as error:
            try:
                winner = self.get_collection(collection_id)
            except BackendUnavailable:
                raise BackendUnavailable() from None
            if winner:
                if winner.get('photo_path') != path:
                    self._remove_evidence(path)
                return winner
            self._remove_evidence(path)
            self._raise_access_or_backend(error)

    def cancel_session(self, session_id, profile_id, legacy_driver):
        try:
            return bool(self.client.rpc('cancel_hub_session', {
                'p_session_id': session_id,
                'p_profile_id': profile_id,
                'p_legacy_driver': legacy_driver,
            }).execute().data)
        except Exception as error:
            self._raise_access_or_backend(error)

    def collect(self, batch_id):
        try:
            self.client.table('dropoffs').update({
                'status': 'collected', 'collected_at': datetime.now(timezone.utc).isoformat()
            }).eq('id', batch_id).eq('status', 'available').execute()
        except Exception:
            raise BackendUnavailable() from None

    def photo(self, path):
        try:
            return self.client.storage.from_('dropoff-evidence').download(path)
        except Exception:
            raise BackendUnavailable() from None
