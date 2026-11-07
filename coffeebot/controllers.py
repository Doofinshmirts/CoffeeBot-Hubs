from collections import deque
from functools import wraps
from io import BytesIO
from threading import Lock
from time import monotonic
from uuid import UUID, uuid4
import secrets

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash
from .models import BackendUnavailable
from .services import parse_weight, prepare_photo

bp = Blueprint('web', __name__)


class LoginThrottle:
    """Single-process demo throttling. Deploy one Gunicorn worker with threads."""
    def __init__(self):
        self.attempts = deque()
        self.lock = Lock()

    def allow(self):
        with self.lock:
            now = monotonic()
            while self.attempts and self.attempts[0] < now - 300:
                self.attempts.popleft()
            if len(self.attempts) >= 10:
                return False
            self.attempts.append(now)
            return True


def repo():
    return current_app.extensions['repository']


def staff_only(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get('staff'):
            return redirect(url_for('web.login'))
        return fn(*args, **kwargs)
    return wrapped


@bp.app_errorhandler(BackendUnavailable)
def backend_error(error):
    if request.path.startswith('/api/'):
        return jsonify(error='Connection interrupted. Retrying shortly.'), 503
    return render_template('error.html', title='Connection interrupted',
                           message='We could not confirm this action. Check your connection and retry; your submission reference prevents duplicates.'), 503


@bp.get('/health')
def health():
    return jsonify(status='ok')


@bp.get('/')
def index():
    hubs, batches = repo().snapshot()
    return render_template('index.html', hubs=hubs,
                           total=sum(h['available_kg'] for h in hubs),
                           initial_ids=[b['id'] for b in batches if b['status'] == 'available'])


@bp.get('/hubs/<int:hub_id>')
def hub(hub_id):
    hubs, batches = repo().snapshot()
    item = next((h for h in hubs if h['id'] == hub_id), None)
    if not item:
        abort(404)
    return render_template('hub.html', hub=item,
                           batches=sorted([b for b in batches if b['hub_id'] == hub_id and b['status'] == 'available'], key=lambda b: b['created_at'], reverse=True))


@bp.get('/api/availability')
def availability():
    hubs, batches = repo().snapshot()
    # Explicit public projection excludes rider identities and private storage paths.
    return jsonify(hubs=[{k: h[k] for k in ('id', 'name', 'available_kg', 'batch_count', 'last_update')} for h in hubs],
                   batches=[{k: b[k] for k in ('id', 'hub_id', 'weight_kg', 'created_at')} for b in batches if b['status'] == 'available'])


@bp.route('/staff/login', methods=['GET', 'POST'])
def login():
    error = None
    status = 200
    if request.method == 'POST':
        if not current_app.extensions['login_throttle'].allow():
            error, status = 'Too many sign-in attempts. Please try again in five minutes.', 429
        else:
            password_hash = current_app.config['STAFF_PASSWORD_HASH']
            valid_password = bool(password_hash) and check_password_hash(password_hash, request.form.get('password', ''))
            if secrets.compare_digest(request.form.get('username', ''), current_app.config['STAFF_USERNAME']) and valid_password:
                session.clear()
                session['staff'] = True
                session.permanent = True
                return redirect(url_for('web.dropoff'))
            error, status = 'Username or password is incorrect.', 401
    return render_template('login.html', error=error), status


@bp.post('/staff/logout')
def logout():
    session.clear()
    return redirect(url_for('web.index'))


@bp.route('/staff/dropoffs/new', methods=['GET', 'POST'])
@staff_only
def dropoff():
    hubs, _ = repo().snapshot()
    values = request.form.to_dict() if request.method == 'POST' else {}
    batch_id = values.get('submission_id') or str(uuid4())
    error = None
    status = 200
    if request.method == 'POST':
        try:
            batch_id = str(UUID(batch_id))
            if repo().get_batch(batch_id):
                return redirect(url_for('web.confirmation', batch_id=batch_id), 303)
            hub_id = int(values.get('hub_id', ''))
            if not any(h['id'] == hub_id for h in hubs):
                raise ValueError('Choose an active hub.')
            source = values.get('rider_source', '').strip()
            if not 1 <= len(source) <= 80:
                raise ValueError('Enter a rider or source name, up to 80 characters.')
            weight = parse_weight(values.get('weight_kg', ''))
            photo = prepare_photo(request.files.get('photo'))
            repo().create_batch(batch_id, hub_id, source, weight, photo)
            return redirect(url_for('web.confirmation', batch_id=batch_id), 303)
        except ValueError as e:
            error = str(e) if str(e) and 'invalid literal' not in str(e) and 'UUID' not in str(e) else 'Please select a hub and reload the form if necessary.'
            status = 400
        except BackendUnavailable:
            error = 'We could not confirm the save. Select your photo again and retry. This same submission reference prevents duplicate records.'
            status = 503
    return render_template('dropoff.html', hubs=hubs, values=values,
                           submission_id=batch_id, error=error), status


@bp.get('/staff/dropoffs/<uuid:batch_id>')
@staff_only
def confirmation(batch_id):
    batch = repo().get_batch(str(batch_id))
    if not batch:
        abort(404)
    hubs, _ = repo().snapshot()
    item = next((h for h in hubs if h['id'] == batch['hub_id']), None)
    return render_template('confirmation.html', batch=batch, hub=item)


@bp.get('/staff/batches')
@staff_only
def manage():
    hubs, batches = repo().snapshot()
    return render_template('manage.html', hubs={h['id']: h for h in hubs},
                           batches=sorted(batches, key=lambda b: b['created_at'], reverse=True))


@bp.post('/staff/batches/<uuid:batch_id>/collect')
@staff_only
def collect(batch_id):
    if not repo().get_batch(str(batch_id)):
        abort(404)
    repo().collect(str(batch_id))
    flash('Batch marked collected. Hub availability is updated.')
    return redirect(url_for('web.manage'), 303)


@bp.get('/staff/batches/<uuid:batch_id>/photo')
@staff_only
def photo(batch_id):
    batch = repo().get_batch(str(batch_id))
    if not batch:
        abort(404)
    # Proxy via the authenticated server: no public URL or credential is exposed.
    return send_file(BytesIO(repo().photo(batch['photo_path'])), mimetype='image/jpeg', max_age=0)
