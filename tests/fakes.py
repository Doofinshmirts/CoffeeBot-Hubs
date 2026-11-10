"""In-memory test doubles only. Never used by app.py or the deployment."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from threading import Lock
from uuid import uuid4

from coffeebot.models import summarize, BackendUnavailable, HubAccessError
from coffeebot.services import AuthRejected


class MemoryRepository:
    def __init__(self):
        self.hubs = [dict(id=i, name=name, address=address, latitude=lat, longitude=lon,
                         instructions='Demo only. Check with the team before a supervised collection.',
                         active=True, is_demo=True, current_weight_kg=Decimal('0'))
            for i, name, address, lat, lon in [
                (1,'Demo Hub A · Campus Corner','Illustrative campus location, Bras Basah',1.2963,103.8502),
                (2,'Demo Hub B · Garden Loop','Illustrative garden location, Fort Canning',1.2950,103.8460),
                (3,'Demo Hub C · Community Table','Illustrative community location, Bencoolen',1.3002,103.8520)]]
        self.batches = {}
        self.collections = {}
        self.sessions = {}
        self.profiles = {}
        self.photos = {}
        self.fail = False
        self.lock = Lock()

    def check(self):
        if self.fail:
            raise BackendUnavailable()

    def snapshot(self):
        self.check()
        batches = list(self.batches.values())
        return summarize(self.hubs, batches, list(self.collections.values())), batches

    def get_hub(self, hub_id):
        self.check()
        return next((hub for hub in self.hubs if hub['id'] == int(hub_id) and hub['active']), None)

    def get_profile(self, profile_id):
        self.check()
        return self.profiles.get(profile_id)

    def get_session(self, session_id):
        self.check()
        return self.sessions.get(session_id)

    def open_session(self, session_id, hub_id, profile_id, legacy_driver, action):
        self.check()
        with self.lock:
            now = datetime.now(timezone.utc)
            for item in self.sessions.values():
                if item['status'] == 'open' and datetime.fromisoformat(item['expires_at']) <= now:
                    item.update(status='expired', closed_at=now.isoformat())
            if any(s['hub_id'] == int(hub_id) and s['status'] == 'open' for s in self.sessions.values()):
                raise HubAccessError('hub_in_use')
            hub = self.get_hub(hub_id)
            if not hub:
                raise HubAccessError('hub_not_found')
            if legacy_driver:
                if action != 'dropoff' or profile_id is not None:
                    raise HubAccessError('role_not_allowed')
            else:
                profile = self.profiles.get(profile_id)
                if not profile or not profile['active']:
                    raise HubAccessError('account_inactive')
                expected = 'dropoff' if profile['role'] == 'driver' else 'collection'
                if action != expected:
                    raise HubAccessError('role_not_allowed')
                if action == 'collection' and Decimal(str(hub['current_weight_kg'])) <= 0:
                    raise HubAccessError('nothing_available')
            row = dict(id=session_id, hub_id=int(hub_id), profile_id=profile_id,
                       legacy_driver=legacy_driver, action=action, status='open',
                       opening_weight_kg=str(hub['current_weight_kg']), opened_at=now.isoformat(),
                       expires_at=(now + timedelta(minutes=5)).isoformat(), closed_at=None)
            self.sessions[session_id] = row
            return row

    def get_batch(self, batch_id):
        self.check()
        return self.batches.get(batch_id)

    def create_batch(self, batch_id, hub_id, source, weight, image):
        self.check()
        with self.lock:
            if batch_id not in self.batches:
                self.batches[batch_id] = dict(id=batch_id, hub_id=hub_id, rider_source=source,
                    weight_kg=str(weight), photo_path=batch_id+'.jpg', created_at=datetime.now(timezone.utc).isoformat(),
                    status='available', collected_at=None, profile_id=None, session_id=None, legacy_driver=True)
                self.photos[batch_id+'.jpg'] = image
                self.get_hub(hub_id)['current_weight_kg'] += Decimal(str(weight))
            return self.batches[batch_id]

    def _validate_session(self, session_id, profile_id, legacy_driver, action):
        item = self.sessions.get(session_id)
        if not item or item['action'] != action:
            raise HubAccessError('invalid_session')
        if item['status'] != 'open':
            raise HubAccessError('session_closed')
        if item['profile_id'] != profile_id or item['legacy_driver'] != legacy_driver:
            raise HubAccessError('session_not_owned')
        if datetime.fromisoformat(item['expires_at']) <= datetime.now(timezone.utc):
            item.update(status='expired', closed_at=datetime.now(timezone.utc).isoformat())
            raise HubAccessError('session_expired')
        return item

    def complete_dropoff(self, session_id, profile_id, legacy_driver, dropoff_id, source, weight, image):
        self.check()
        with self.lock:
            if dropoff_id in self.batches:
                return self.batches[dropoff_id]
            access = self._validate_session(session_id, profile_id, legacy_driver, 'dropoff')
            path = f'dropoffs/{dropoff_id}.jpg'
            row = dict(id=dropoff_id, hub_id=access['hub_id'], rider_source=source,
                       weight_kg=str(weight), photo_path=path, created_at=datetime.now(timezone.utc).isoformat(),
                       status='available', collected_at=None, profile_id=profile_id,
                       session_id=session_id, legacy_driver=legacy_driver)
            self.batches[dropoff_id] = row
            self.photos[path] = image
            self.get_hub(access['hub_id'])['current_weight_kg'] += Decimal(str(weight))
            access.update(status='completed', closed_at=datetime.now(timezone.utc).isoformat())
            return row

    def get_collection(self, collection_id):
        self.check()
        return self.collections.get(collection_id)

    def complete_collection(self, session_id, profile_id, collection_id, remaining_weight, image):
        self.check()
        with self.lock:
            if collection_id in self.collections:
                return self.collections[collection_id]
            access = self._validate_session(session_id, profile_id, False, 'collection')
            hub = self.get_hub(access['hub_id'])
            before = Decimal(str(hub['current_weight_kg']))
            after = Decimal(str(remaining_weight))
            if after < 0 or after >= before:
                raise HubAccessError('invalid_remaining_weight')
            path = f'collections/{collection_id}.jpg'
            row = dict(id=collection_id, session_id=session_id, hub_id=access['hub_id'],
                       profile_id=profile_id, weight_before_kg=str(before),
                       weight_after_kg=str(after), collected_kg=str(before-after),
                       photo_path=path, created_at=datetime.now(timezone.utc).isoformat())
            self.collections[collection_id] = row
            self.photos[path] = image
            hub['current_weight_kg'] = after
            access.update(status='completed', closed_at=datetime.now(timezone.utc).isoformat())
            return row

    def cancel_session(self, session_id, profile_id, legacy_driver):
        self.check()
        with self.lock:
            item = self.sessions.get(session_id)
            if not item or item['profile_id'] != profile_id or item['legacy_driver'] != legacy_driver:
                return False
            if item['status'] == 'open':
                item.update(status='cancelled', closed_at=datetime.now(timezone.utc).isoformat())
            return True

    def collect(self, batch_id):
        self.check()
        with self.lock:
            if self.batches[batch_id]['status'] == 'available':
                self.batches[batch_id].update(status='collected', collected_at=datetime.now(timezone.utc).isoformat())

    def photo(self, path):
        self.check()
        return self.photos[path]


class FakeAuthService:
    def __init__(self, repository):
        self.repository = repository
        self.users = {}

    def register(self, email, password, profile):
        if email in self.users:
            raise AuthRejected()
        user_id = str(uuid4())
        self.users[email] = {'id': user_id, 'password': password}
        self.repository.profiles[user_id] = {
            'id': user_id, 'email': email, 'role': 'community',
            'account_type': profile['account_type'], 'full_name': profile['full_name'],
            'phone': profile['phone'], 'organization_name': profile.get('organization_name'),
            'organization_type': profile.get('organization_type'), 'active': True,
        }
        return {'user_id': user_id, 'confirmation_required': False}

    def authenticate(self, email, password):
        user = self.users.get(email)
        if not user or user['password'] != password:
            raise AuthRejected()
        return {'user_id': user['id'], 'email': email}
