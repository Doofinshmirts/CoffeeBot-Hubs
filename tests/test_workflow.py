import re
from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID

import pytest
from PIL import Image
from werkzeug.security import generate_password_hash

from coffeebot import create_app
from coffeebot.services import parse_remaining_weight, parse_weight, prepare_photo
from .fakes import FakeAuthService, MemoryRepository


@pytest.fixture
def setup():
    repository = MemoryRepository()
    auth = FakeAuthService(repository)
    app = create_app({
        'TESTING': True,
        'SECRET_KEY': 'test-secret-not-for-production',
        'STAFF_PASSWORD_HASH': generate_password_hash('test-password-123'),
        'SESSION_COOKIE_SECURE': False,
    }, repository, auth)
    return app, repository, auth


def token(client, path):
    page = client.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token" value="([^"]+)"', page)
    assert match, path
    return match.group(1)


def driver_login(client, password='test-password-123'):
    return client.post('/staff/login', data={
        'csrf_token': token(client, '/staff/login'), 'username': 'driver', 'password': password,
    })


def register(client, account_type='individual', **changes):
    data = {
        'csrf_token': token(client, '/account/register'),
        'account_type': account_type,
        'full_name': 'Community User',
        'phone': '+65 8123 4567',
        'email': 'user@example.com',
        'password': 'community-pass-123',
        'password_confirm': 'community-pass-123',
        'responsible_use': 'yes',
    }
    if account_type == 'organization':
        data.update(organization_name='Demo School', organization_type='school')
    data.update(changes)
    return client.post('/account/register', data=data)


def community_login(client, email='user@example.com', password='community-pass-123'):
    return client.post('/account/login', data={
        'csrf_token': token(client, '/account/login'), 'email': email, 'password': password,
    })


def image():
    output = BytesIO()
    Image.new('RGB', (100, 100), '#72533e').save(output, 'JPEG')
    output.seek(0)
    return output


def open_hub(client, hub_id=1):
    response = client.post(f'/hubs/{hub_id}/open', data={
        'csrf_token': token(client, f'/hubs/{hub_id}/access'),
    })
    assert response.status_code == 303
    assert '/hub-sessions/' in response.headers['Location']
    return response.headers['Location']


def finish_dropoff(client, session_path, weight='5', source='Demo rider', photo=None):
    return client.post(session_path, data={
        'csrf_token': token(client, session_path),
        'rider_source': source,
        'weight_kg': weight,
        'photo': (photo or image(), 'grounds.jpg'),
    }, content_type='multipart/form-data')


def finish_collection(client, session_path, remaining='2', photo=None):
    return client.post(session_path, data={
        'csrf_token': token(client, session_path),
        'remaining_weight_kg': remaining,
        'photo': (photo or image(), 'remaining.jpg'),
    }, content_type='multipart/form-data')


def seed_inventory(app):
    driver = app.test_client()
    assert driver_login(driver).status_code == 302
    path = open_hub(driver)
    assert finish_dropoff(driver, path).status_code == 303
    return driver


def test_driver_dropoff_and_public_privacy(setup):
    app, repository, _ = setup
    driver, community = app.test_client(), app.test_client()
    assert driver_login(driver).status_code == 302
    session_path = open_hub(driver)
    assert 'Lid open' in driver.get(session_path).get_data(as_text=True)
    assert finish_dropoff(driver, session_path).status_code == 303
    assert len(repository.batches) == 1
    assert repository.hubs[0]['current_weight_kg'] == 5
    access = next(iter(repository.sessions.values()))
    assert access['status'] == 'completed'
    snapshot = community.get('/api/availability').get_json()
    assert snapshot['hubs'][0]['available_kg'] == 5
    assert 'rider_source' not in str(snapshot)
    assert 'photo_path' not in str(snapshot)
    assert 'profile_id' not in str(snapshot)
    batch_id = next(iter(repository.batches))
    assert community.get(f'/staff/batches/{batch_id}/photo').status_code == 302


def test_individual_registration_and_partial_collection(setup):
    app, repository, _ = setup
    seed_inventory(app)
    user = app.test_client()
    assert register(user).status_code == 302
    assert community_login(user).status_code == 302
    session_path = open_hub(user)
    page = user.get(session_path).get_data(as_text=True)
    assert 'Starting scale weight' in page and '5 kg' in page
    response = finish_collection(user, session_path, remaining='2')
    assert response.status_code == 303
    event = next(iter(repository.collections.values()))
    assert event['collected_kg'] == '3'
    assert repository.hubs[0]['current_weight_kg'] == 2
    assert repository.sessions[str(UUID(session_path.rsplit('/', 1)[-1]))]['status'] == 'completed'
    assert '3 <small>kg collected</small>' in user.get(response.headers['Location']).get_data(as_text=True)
    public = user.get('/api/availability').get_json()
    assert public['hubs'][0]['deposit_count'] == 1
    assert 'batch_count' not in public['hubs'][0]
    assert '1</span> recorded deposits' in user.get('/').get_data(as_text=True)


def test_organization_registration(setup):
    app, repository, _ = setup
    client = app.test_client()
    assert register(client, 'organization', email='school@example.com').status_code == 302
    profile = next(p for p in repository.profiles.values() if p['email'] == 'school@example.com')
    assert profile['account_type'] == 'organization'
    assert profile['organization_name'] == 'Demo School'
    assert profile['role'] == 'community'


@pytest.mark.parametrize('changes', [
    {'account_type': 'driver'},
    {'full_name': ''},
    {'phone': ''},
    {'email': 'invalid'},
    {'password': 'short', 'password_confirm': 'short'},
    {'password_confirm': 'different-password'},
    {'responsible_use': ''},
])
def test_registration_validation_and_no_driver_escalation(setup, changes):
    app, repository, _ = setup
    response = register(app.test_client(), **changes)
    assert response.status_code == 400
    assert not repository.profiles


def test_organization_fields_required(setup):
    app, repository, _ = setup
    response = register(app.test_client(), 'organization', organization_name='', organization_type='')
    assert response.status_code == 400
    assert not repository.profiles


@pytest.mark.parametrize('remaining', ['-1', '5', '6', '1.001', 'NaN', 'Infinity', 'abc', ''])
def test_invalid_remaining_weight(remaining):
    with pytest.raises(ValueError):
        parse_remaining_weight(remaining, '5')


@pytest.mark.parametrize('weight', ['0', '-1', 'NaN', 'Infinity', '11', '1.001', 'abc', ''])
def test_invalid_dropoff_weight(weight):
    with pytest.raises(ValueError):
        parse_weight(weight)


def test_only_one_open_session_per_hub(setup):
    app, _, _ = setup
    first, second = app.test_client(), app.test_client()
    driver_login(first)
    driver_login(second)
    open_hub(first)
    response = second.post('/hubs/1/open', data={'csrf_token': token(second, '/hubs/1/access')})
    assert response.status_code == 303
    assert 'currently in use' in second.get(response.headers['Location']).get_data(as_text=True)


def test_login_rejects_backslash_external_next(setup):
    app, _, _ = setup
    client = app.test_client()
    assert register(client).status_code == 302
    response = client.post('/account/login', data={
        'csrf_token': token(client, '/account/login?next=/\\evil.example'),
        'email': 'user@example.com',
        'password': 'community-pass-123',
        'next': '/\\evil.example',
    })
    assert response.status_code == 302
    assert response.headers['Location'] == '/'


def test_expired_session_locks_without_inventory_change(setup):
    app, repository, _ = setup
    driver = app.test_client()
    driver_login(driver)
    path = open_hub(driver)
    access = next(iter(repository.sessions.values()))
    access['expires_at'] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    response = finish_dropoff(driver, path)
    assert response.status_code == 400
    assert access['status'] == 'expired'
    assert repository.hubs[0]['current_weight_kg'] == 0
    assert not repository.batches


def test_wrong_account_cannot_use_session(setup):
    app, _, _ = setup
    seed_inventory(app)
    first, second = app.test_client(), app.test_client()
    register(first)
    community_login(first)
    register(second, email='second@example.com')
    community_login(second, email='second@example.com')
    path = open_hub(first)
    assert second.get(path).status_code == 403


def test_validation_does_not_change_inventory_or_close_session(setup):
    app, repository, _ = setup
    driver = app.test_client()
    driver_login(driver)
    path = open_hub(driver)
    response = finish_dropoff(driver, path, weight='-1')
    assert response.status_code == 400
    assert repository.hubs[0]['current_weight_kg'] == 0
    access = next(iter(repository.sessions.values()))
    assert access['status'] == 'open'


def test_duplicate_completion_is_idempotent(setup):
    app, repository, _ = setup
    driver = app.test_client()
    driver_login(driver)
    path = open_hub(driver)
    response = finish_dropoff(driver, path)
    assert response.status_code == 303
    assert finish_dropoff(driver, path).status_code == 303
    assert len(repository.batches) == 1
    assert repository.hubs[0]['current_weight_kg'] == 5


def test_cancel_locks_session(setup):
    app, repository, _ = setup
    driver = app.test_client()
    driver_login(driver)
    path = open_hub(driver)
    response = driver.post(path + '/cancel', data={'csrf_token': token(driver, path)})
    assert response.status_code == 303
    assert next(iter(repository.sessions.values()))['status'] == 'cancelled'


def test_csrf_logout_throttling_and_inactive_account(setup):
    app, repository, _ = setup
    client = app.test_client()
    assert client.post('/staff/login', data={'username': 'driver', 'password': 'test-password-123'}).status_code == 400
    register(client)
    profile = next(iter(repository.profiles.values()))
    profile['active'] = False
    assert community_login(client).status_code == 401
    for _ in range(9):
        response = client.post('/staff/login', data={
            'csrf_token': token(client, '/staff/login'), 'username': 'driver', 'password': 'wrong',
        })
        assert response.status_code == 401
    response = client.post('/staff/login', data={
        'csrf_token': token(client, '/staff/login'), 'username': 'driver', 'password': 'wrong',
    })
    assert response.status_code == 429


def test_outage_and_security_headers(setup):
    app, repository, _ = setup
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    repository.fail = True
    assert client.get('/api/availability').status_code == 503
    assert client.get('/').status_code == 503


def test_invalid_and_oversized_photo():
    with pytest.raises(ValueError):
        prepare_photo(type('Upload', (), {'filename': 'fake.jpg', 'read': lambda self, size: b'bad'})())
    with pytest.raises(ValueError):
        prepare_photo(type('Upload', (), {'filename': 'huge.jpg',
                      'read': lambda self, size: b'x' * (10 * 1024 * 1024 + 1)})())


def test_all_pages_render(setup):
    app, _, _ = setup
    client = app.test_client()
    for path in ['/', '/hubs/1', '/hubs/2', '/hubs/3', '/staff/login', '/account/login', '/account/register']:
        assert client.get(path).status_code == 200
    assert client.get('/hubs/999').status_code == 404
    assert client.get('/hubs/1/access').status_code == 302
    driver_login(client)
    assert client.get('/hubs/1/access').status_code == 200
    assert client.get('/staff/batches').status_code == 200
