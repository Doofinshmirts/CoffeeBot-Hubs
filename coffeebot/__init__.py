import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, render_template, request
from flask_wtf.csrf import CSRFProtect, CSRFError


def create_app(config=None, repository=None, auth_service=None):
    load_dotenv(Path(__file__).resolve().parent.parent / '.env', interpolate=False)
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get('SECRET_KEY'),
        STAFF_USERNAME=os.environ.get('STAFF_USERNAME', 'driver'),
        STAFF_PASSWORD_HASH=os.environ.get('STAFF_PASSWORD_HASH', ''),
        SUPABASE_URL=os.environ.get('SUPABASE_URL', ''),
        SUPABASE_SECRET_KEY=os.environ.get('SUPABASE_SECRET_KEY', ''),
        SUPABASE_PUBLISHABLE_KEY=os.environ.get('SUPABASE_PUBLISHABLE_KEY', ''),
        APP_URL=os.environ.get('APP_URL', 'http://127.0.0.1:5000'),
        MAX_CONTENT_LENGTH=11 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
        SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', 'false').lower() == 'true',
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
        WTF_CSRF_TIME_LIMIT=4 * 60 * 60,
    )
    if config:
        app.config.update(config)
    if not app.config['SECRET_KEY']:
        raise RuntimeError('Set SECRET_KEY in .env. See README for local setup.')
    if repository is None:
        from .models import SupabaseRepository
        repository = SupabaseRepository(app.config['SUPABASE_URL'], app.config['SUPABASE_SECRET_KEY'])
    if auth_service is None:
        from .services import SupabaseAuthService
        auth_service = SupabaseAuthService(
            app.config['SUPABASE_URL'], app.config['SUPABASE_PUBLISHABLE_KEY'],
            app.config['APP_URL'].rstrip('/') + '/account/login',
        )
    app.extensions['repository'] = repository
    app.extensions['auth_service'] = auth_service
    CSRFProtect(app)
    from .controllers import bp, LoginThrottle
    app.extensions['login_throttle'] = LoginThrottle()
    app.register_blueprint(bp)

    @app.template_filter('sgtime')
    def sgtime(value):
        if not value:
            return 'No drop-offs yet'
        instant = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return instant.astimezone(timezone(timedelta(hours=8))).strftime('%d %b, %H:%M SGT')

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        return render_template('error.html', title='Please refresh this page',
                               message='Your form expired. Reload the form and try again.'), 400

    @app.errorhandler(413)
    def too_large(error):
        return render_template('error.html', title='That photo is too large',
                               message='Choose a JPEG, PNG or WebP photo under 10 MB.'), 413

    @app.errorhandler(404)
    def missing(error):
        return render_template('error.html', title='Page not found',
                               message='This hub or batch could not be found.'), 404

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' blob: data:; font-src 'self'; connect-src 'self'; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        if not request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    return app
