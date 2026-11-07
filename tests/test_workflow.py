import re
from io import BytesIO
from uuid import uuid4
import pytest
from PIL import Image
from werkzeug.security import generate_password_hash
from coffeebot import create_app
from coffeebot.services import parse_weight, prepare_photo
from .fakes import MemoryRepository


@pytest.fixture
def setup():
    repository = MemoryRepository()
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret-not-for-production',
        'STAFF_PASSWORD_HASH': generate_password_hash('test-password-123'), 'SESSION_COOKIE_SECURE': False}, repository)
    return app, repository


def token(client, path):
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)


def login(client):
    return client.post('/staff/login', data={'csrf_token': token(client, '/staff/login'),
        'username': 'driver', 'password': 'test-password-123'})


def image():
    output = BytesIO()
    Image.new('RGB', (100, 100), '#72533e').save(output, 'JPEG')
    output.seek(0)
    return output


def submit(client, batch_id=None, **changes):
    data = {'csrf_token': token(client, '/staff/dropoffs/new'), 'submission_id': batch_id or str(uuid4()),
        'hub_id': '1', 'rider_source': 'Demo rider', 'weight_kg': '5', 'photo': (image(), 'grounds.jpg')}
    data.update(changes)
    return client.post('/staff/dropoffs/new', data=data, content_type='multipart/form-data')


def test_complete_workflow_and_privacy(setup):
    app, repository = setup
    staff, community = app.test_client(), app.test_client()
    assert login(staff).status_code == 302
    batch_id = str(uuid4())
    assert submit(staff, batch_id).status_code == 303
    assert len(repository.batches) == 1
    snapshot = community.get('/api/availability').get_json()
    assert snapshot['hubs'][0]['available_kg'] == 5
    assert snapshot['batches'][0]['id'] == batch_id
    assert 'rider_source' not in str(snapshot) and 'photo_path' not in str(snapshot)
    assert community.get(f'/staff/batches/{batch_id}/photo').status_code == 302
    assert staff.get(f'/staff/batches/{batch_id}/photo').mimetype == 'image/jpeg'
    assert submit(staff, batch_id).status_code == 303
    assert len(repository.batches) == 1
    for _ in range(2):
        assert staff.post(f'/staff/batches/{batch_id}/collect', data={'csrf_token':token(staff,'/staff/batches')}).status_code == 303
    assert community.get('/api/availability').get_json()['hubs'][0]['available_kg'] == 0
    assert repository.batches[batch_id]['status'] == 'collected'


@pytest.mark.parametrize('weight', ['0','-1','NaN','Infinity','11','1.001','abc',''])
def test_invalid_weight(weight):
    with pytest.raises(ValueError):
        parse_weight(weight)


def test_validation_and_csrf(setup):
    app, repository = setup
    client = app.test_client()
    assert client.post('/staff/login', data={'username':'driver','password':'test-password-123'}).status_code == 400
    login(client)
    assert submit(client, weight_kg='-1').status_code == 400
    assert submit(client, photo=(BytesIO(b'not an image'),'fake.jpg')).status_code == 400
    assert submit(client, photo=(BytesIO(b''),'')).status_code == 400
    assert submit(client, hub_id='999').status_code == 400
    assert submit(client, rider_source='').status_code == 400
    assert not repository.batches


def test_logout_and_throttling(setup):
    app, _ = setup
    client = app.test_client()
    login(client)
    client.post('/staff/logout', data={'csrf_token': token(client,'/staff/batches')})
    assert client.get('/staff/batches').status_code == 302
    for _ in range(9):
        response = client.post('/staff/login', data={'csrf_token':token(client,'/staff/login'),'username':'driver','password':'wrong'})
        assert response.status_code == 401
    response = client.post('/staff/login', data={'csrf_token':token(client,'/staff/login'),'username':'driver','password':'wrong'})
    assert response.status_code == 429


def test_outage_and_security_headers(setup):
    app, repository = setup
    client = app.test_client()
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    repository.fail = True
    assert client.get('/api/availability').status_code == 503
    assert client.get('/').status_code == 503


def test_oversized_photo(setup):
    app, repository = setup
    client = app.test_client(); login(client)
    response = submit(client, photo=(BytesIO(b'x' * (10*1024*1024+1)),'huge.jpg'))
    assert response.status_code == 400
    assert not repository.batches


def test_all_pages_render(setup):
    app, _ = setup
    client = app.test_client()
    for path in ['/', '/hubs/1', '/hubs/2', '/hubs/3', '/staff/login']:
        assert client.get(path).status_code == 200
    assert client.get('/hubs/999').status_code == 404
    login(client)
    for path in ['/staff/dropoffs/new','/staff/batches']:
        assert client.get(path).status_code == 200
    response = submit(client)
    assert client.get(response.headers['Location']).status_code == 200
