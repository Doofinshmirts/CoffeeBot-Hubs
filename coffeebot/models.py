"""Database access is restricted to this module; no credentials enter templates."""
from datetime import datetime, timezone
from decimal import Decimal
from supabase import create_client


class BackendUnavailable(Exception):
    pass


def summarize(hubs, batches):
    result = []
    for hub in hubs:
        rows = [b for b in batches if b['hub_id'] == hub['id']]
        available = [b for b in rows if b['status'] == 'available']
        result.append({**hub,
            'available_kg': float(sum((Decimal(str(b['weight_kg'])) for b in available), Decimal('0'))),
            'batch_count': len(available),
            'last_update': max((b['created_at'] for b in rows), default=None)})
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
            active_ids = {h['id'] for h in hubs}
            batches = [b for b in batches if b['hub_id'] in active_ids]
            return summarize(hubs, batches), batches
        except Exception:
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
