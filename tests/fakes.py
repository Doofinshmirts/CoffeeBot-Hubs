"""In-memory test double only. Never used by app.py or the deployment."""
from datetime import datetime, timezone
from decimal import Decimal
from threading import Lock
from coffeebot.models import summarize, BackendUnavailable


class MemoryRepository:
    def __init__(self):
        self.hubs = [dict(id=i, name=name, address=address, latitude=lat, longitude=lon,
                         instructions='Demo only. Check with the team before a supervised collection.', active=True, is_demo=True)
            for i, name, address, lat, lon in [
                (1,'Demo Hub A · Campus Corner','Illustrative campus location, Bras Basah',1.2963,103.8502),
                (2,'Demo Hub B · Garden Loop','Illustrative garden location, Fort Canning',1.2950,103.8460),
                (3,'Demo Hub C · Community Table','Illustrative community location, Bencoolen',1.3002,103.8520)]]
        self.batches = {}
        self.photos = {}
        self.fail = False
        self.lock = Lock()

    def check(self):
        if self.fail:
            raise BackendUnavailable()

    def snapshot(self):
        self.check()
        batches = list(self.batches.values())
        return summarize(self.hubs, batches), batches

    def get_batch(self, batch_id):
        self.check()
        return self.batches.get(batch_id)

    def create_batch(self, batch_id, hub_id, source, weight, image):
        self.check()
        with self.lock:
            if batch_id not in self.batches:
                self.batches[batch_id] = dict(id=batch_id, hub_id=hub_id, rider_source=source,
                    weight_kg=str(weight), photo_path=batch_id+'.jpg', created_at=datetime.now(timezone.utc).isoformat(),
                    status='available', collected_at=None)
                self.photos[batch_id+'.jpg'] = image
            return self.batches[batch_id]

    def collect(self, batch_id):
        self.check()
        with self.lock:
            if self.batches[batch_id]['status'] == 'available':
                self.batches[batch_id].update(status='collected', collected_at=datetime.now(timezone.utc).isoformat())

    def photo(self, path):
        self.check()
        return self.photos[path]
