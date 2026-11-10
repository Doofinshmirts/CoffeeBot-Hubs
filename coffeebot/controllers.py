from collections import deque
from functools import wraps
from io import BytesIO
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit
from uuid import uuid4
import secrets

from flask import (
    Blueprint, abort, current_app, flash, jsonify, redirect, render_template,
    request, send_file, session, url_for,
)
from werkzeug.security import check_password_hash

from .models import BackendUnavailable, HubAccessError
from .services import (
    AuthRejected, AuthUnavailable, parse_remaining_weight, parse_weight, prepare_photo,
)

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


def auth_service():
    return current_app.extensions['auth_service']


def safe_next(value, fallback):
    if not value or '\\' in value:
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/') or parsed.path.startswith('//'):
        return fallback
    return value


def current_actor():
    if session.get('staff'):
        return {
            'profile_id': None,
            'role': 'driver',
            'display_name': current_app.config['STAFF_USERNAME'],
            'legacy_driver': True,
        }
    profile_id = session.get('user_id')
    if not profile_id:
        return None
    profile = repo().get_profile(profile_id)
    if not profile or not profile.get('active'):
        session.clear()
        return None
    session['role'] = profile['role']
    return {
        'profile_id': profile['id'],
        'role': profile['role'],
        'display_name': profile['full_name'],
        'legacy_driver': False,
        'account_type': profile['account_type'],
    }


def actor_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        actor = current_actor()
        if not actor:
            return redirect(url_for('web.account_login', next=request.path))
        return fn(*args, actor=actor, **kwargs)
    return wrapped


def staff_only(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        actor = current_actor()
        if not actor or actor['role'] != 'driver':
            return redirect(url_for('web.staff_login'))
        return fn(*args, **kwargs)
    return wrapped


def owned_access_session(session_id, actor):
    access = repo().get_session(str(session_id))
    if not access:
        abort(404)
    if bool(access['legacy_driver']) != bool(actor['legacy_driver']):
        abort(403)
    if not actor['legacy_driver'] and access['profile_id'] != actor['profile_id']:
        abort(403)
    if actor['legacy_driver'] and access['action'] != 'dropoff':
        abort(403)
    return access


ACCESS_MESSAGES = {
    'hub_in_use': 'This hub is currently in use. Try again after the active session closes.',
    'hub_not_found': 'That hub is unavailable.',
    'role_not_allowed': 'This account cannot perform that action.',
    'account_inactive': 'This account is inactive. Contact the CoffeeBot team.',
    'nothing_available': 'There are currently no grounds available at this hub.',
    'invalid_session': 'This hub session is invalid. Return to the hub and start again.',
    'session_closed': 'This hub session is already closed.',
    'session_expired': 'The five-minute hub session expired. The simulated lid is locked again.',
    'session_not_owned': 'This hub session belongs to another account.',
    'invalid_weight': 'Enter a valid drop-off weight.',
    'invalid_remaining_weight': 'The remaining weight must be lower than the starting weight.',
}


@bp.app_errorhandler(BackendUnavailable)
def backend_error(error):
    if request.path.startswith('/api/'):
        return jsonify(error='Connection interrupted. Retrying shortly.'), 503
    return render_template(
        'error.html', title='Connection interrupted',
        message='We could not confirm this action. Check your connection and retry; no inventory change was confirmed.'
    ), 503


@bp.app_errorhandler(403)
def forbidden(error):
    return render_template('error.html', title='Access denied',
                           message='This account cannot access that hub session or evidence.'), 403


@bp.get('/health')
def health():
    return jsonify(status='ok')


@bp.get('/')
def index():
    hubs, batches = repo().snapshot()
    return render_template(
        'index.html', hubs=hubs, total=sum(h['available_kg'] for h in hubs),
        initial_ids=[b['id'] for b in batches if b['status'] == 'available'],
    )


@bp.get('/hubs/<int:hub_id>')
def hub(hub_id):
    hubs, batches = repo().snapshot()
    item = next((h for h in hubs if h['id'] == hub_id), None)
    if not item:
        abort(404)
    return render_template(
        'hub.html', hub=item,
        batches=sorted(
            [b for b in batches if b['hub_id'] == hub_id and b['status'] == 'available'],
            key=lambda b: b['created_at'], reverse=True,
        ),
    )


@bp.get('/api/availability')
def availability():
    hubs, batches = repo().snapshot()
    return jsonify(
        hubs=[{k: h[k] for k in ('id', 'name', 'available_kg', 'deposit_count', 'last_update')} for h in hubs],
        batches=[{k: b[k] for k in ('id', 'hub_id', 'weight_kg', 'created_at')}
                 for b in batches if b['status'] == 'available'],
    )


@bp.route('/account/register', methods=['GET', 'POST'])
def account_register():
    values = request.form.to_dict() if request.method == 'POST' else {}
    error = None
    status = 200
    if request.method == 'POST':
        try:
            account_type = values.get('account_type', '')
            full_name = values.get('full_name', '').strip()
            phone = values.get('phone', '').strip()
            email = values.get('email', '').strip().lower()
            password = values.get('password', '')
            organization_name = values.get('organization_name', '').strip() or None
            organization_type = values.get('organization_type', '') or None
            if account_type not in ('individual', 'organization'):
                raise ValueError('Choose an individual or organization account.')
            if not 2 <= len(full_name) <= 100:
                raise ValueError('Enter a contact name between 2 and 100 characters.')
            if not 6 <= len(phone) <= 30:
                raise ValueError('Enter a contact phone number between 6 and 30 characters.')
            if '@' not in email or len(email) > 320:
                raise ValueError('Enter a valid email address.')
            if len(password) < 12:
                raise ValueError('Use a password with at least 12 characters.')
            if password != values.get('password_confirm', ''):
                raise ValueError('The passwords do not match.')
            if account_type == 'organization':
                if not organization_name or not 2 <= len(organization_name) <= 120:
                    raise ValueError('Enter the organization name.')
                if organization_type not in ('school', 'company', 'nonprofit', 'community_group', 'other'):
                    raise ValueError('Choose the organization type.')
            else:
                organization_name = organization_type = None
            if values.get('responsible_use') != 'yes':
                raise ValueError('Confirm that you will use the hub responsibly.')

            result = auth_service().register(email, password, {
                'account_type': account_type,
                'full_name': full_name,
                'phone': phone,
                'organization_name': organization_name,
                'organization_type': organization_type,
            })
            if result['confirmation_required']:
                flash('Account created. Confirm your email, then return here to sign in.')
            else:
                flash('Account created. You can now sign in.')
            return redirect(url_for('web.account_login'))
        except ValueError as exc:
            error, status = str(exc), 400
        except AuthRejected:
            error, status = 'We could not create that account. Check the details or try a different email.', 400
        except AuthUnavailable:
            error, status = 'Account registration is temporarily unavailable. Please try again shortly.', 503
    return render_template('register.html', values=values, error=error), status


@bp.route('/account/login', methods=['GET', 'POST'])
def account_login():
    error = None
    status = 200
    next_url = safe_next(request.values.get('next'), url_for('web.index'))
    if request.method == 'POST':
        if not current_app.extensions['login_throttle'].allow():
            error, status = 'Too many sign-in attempts. Please try again in five minutes.', 429
        else:
            try:
                identity = auth_service().authenticate(
                    request.form.get('email', '').strip().lower(), request.form.get('password', '')
                )
                profile = repo().get_profile(identity['user_id'])
                if not profile or not profile.get('active'):
                    raise AuthRejected()
                session.clear()
                session['user_id'] = profile['id']
                session['role'] = profile['role']
                session.permanent = True
                return redirect(next_url)
            except AuthRejected:
                error, status = 'Email or password is incorrect, unconfirmed, or the account is inactive.', 401
            except AuthUnavailable:
                error, status = 'Sign-in is temporarily unavailable. Please try again shortly.', 503
    return render_template('account_login.html', error=error, next_url=next_url), status


@bp.route('/staff/login', methods=['GET', 'POST'])
def staff_login():
    error = None
    status = 200
    if request.method == 'POST':
        if not current_app.extensions['login_throttle'].allow():
            error, status = 'Too many sign-in attempts. Please try again in five minutes.', 429
        else:
            password_hash = current_app.config['STAFF_PASSWORD_HASH']
            valid_password = bool(password_hash) and check_password_hash(
                password_hash, request.form.get('password', '')
            )
            if (secrets.compare_digest(request.form.get('username', ''), current_app.config['STAFF_USERNAME'])
                    and valid_password):
                session.clear()
                session['staff'] = True
                session.permanent = True
                return redirect(url_for('web.index'))
            error, status = 'Username or password is incorrect.', 401
    return render_template('login.html', error=error), status


@bp.post('/account/logout')
@bp.post('/staff/logout')
def logout():
    session.clear()
    return redirect(url_for('web.index'))


@bp.get('/hubs/<int:hub_id>/access')
@actor_required
def hub_access(hub_id, actor):
    item = repo().get_hub(hub_id)
    if not item:
        abort(404)
    action = 'dropoff' if actor['role'] == 'driver' else 'collection'
    return render_template('hub_access.html', hub=item, actor=actor, action=action)


@bp.post('/hubs/<int:hub_id>/open')
@actor_required
def open_hub(hub_id, actor):
    action = 'dropoff' if actor['role'] == 'driver' else 'collection'
    access_id = str(uuid4())
    try:
        repo().open_session(access_id, hub_id, actor['profile_id'], actor['legacy_driver'], action)
        return redirect(url_for('web.access_session', session_id=access_id), 303)
    except HubAccessError as exc:
        flash(ACCESS_MESSAGES.get(exc.code, 'The hub could not be opened.'))
        return redirect(url_for('web.hub_access', hub_id=hub_id), 303)


@bp.route('/hub-sessions/<uuid:session_id>', methods=['GET', 'POST'])
@actor_required
def access_session(session_id, actor):
    access = owned_access_session(session_id, actor)
    item = repo().get_hub(access['hub_id'])
    if not item:
        abort(404)
    values = request.form.to_dict() if request.method == 'POST' else {}
    error = None
    status = 200
    if request.method == 'POST':
        try:
            event_id = str(session_id)
            photo = prepare_photo(request.files.get('photo'))
            if access['action'] == 'dropoff':
                source = values.get('rider_source', '').strip()
                if not 1 <= len(source) <= 80:
                    raise ValueError('Enter a rider or source name, up to 80 characters.')
                weight = parse_weight(values.get('weight_kg', ''))
                repo().complete_dropoff(
                    str(session_id), actor['profile_id'], actor['legacy_driver'],
                    event_id, source, weight, photo,
                )
            else:
                remaining = parse_remaining_weight(
                    values.get('remaining_weight_kg', ''), access['opening_weight_kg']
                )
                repo().complete_collection(
                    str(session_id), actor['profile_id'], event_id, remaining, photo,
                )
            return redirect(url_for('web.access_confirmation', session_id=session_id), 303)
        except ValueError as exc:
            error, status = str(exc), 400
        except HubAccessError as exc:
            error = ACCESS_MESSAGES.get(exc.code, 'The action could not be confirmed.')
            status = 409 if exc.code in ('hub_in_use', 'session_closed') else 400
    return render_template(
        'access_session.html', access=access, hub=item, actor=actor,
        values=values, error=error,
    ), status


@bp.post('/hub-sessions/<uuid:session_id>/cancel')
@actor_required
def cancel_access_session(session_id, actor):
    access = owned_access_session(session_id, actor)
    repo().cancel_session(str(session_id), actor['profile_id'], actor['legacy_driver'])
    flash('The simulated lid is locked and the scale is off.')
    return redirect(url_for('web.hub_access', hub_id=access['hub_id']), 303)


@bp.get('/hub-sessions/<uuid:session_id>/confirmation')
@actor_required
def access_confirmation(session_id, actor):
    access = owned_access_session(session_id, actor)
    if access['status'] != 'completed':
        return redirect(url_for('web.access_session', session_id=session_id))
    item = repo().get_hub(access['hub_id'])
    event = (repo().get_batch(str(session_id)) if access['action'] == 'dropoff'
             else repo().get_collection(str(session_id)))
    if not item or not event:
        abort(404)
    return render_template('access_confirmation.html', access=access, hub=item, event=event)


@bp.get('/staff/dropoffs/new')
@staff_only
def legacy_dropoff_redirect():
    flash('Choose a hub first, then use Open lid to begin the simulated scale session.')
    return redirect(url_for('web.index'))


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
    return render_template(
        'manage.html', hubs={h['id']: h for h in hubs},
        batches=sorted(batches, key=lambda b: b['created_at'], reverse=True),
    )


@bp.post('/staff/batches/<uuid:batch_id>/collect')
@staff_only
def legacy_collect_retired(batch_id):
    flash('Use an authenticated community hub session to record a collection and remaining weight.')
    return redirect(url_for('web.manage'), 303)


@bp.get('/staff/batches/<uuid:batch_id>/photo')
@staff_only
def photo(batch_id):
    batch = repo().get_batch(str(batch_id))
    if not batch:
        abort(404)
    return send_file(BytesIO(repo().photo(batch['photo_path'])), mimetype='image/jpeg', max_age=0)


@bp.get('/staff/collections/<uuid:collection_id>/photo')
@staff_only
def collection_photo(collection_id):
    event = repo().get_collection(str(collection_id))
    if not event:
        abort(404)
    return send_file(BytesIO(repo().photo(event['photo_path'])), mimetype='image/jpeg', max_age=0)
