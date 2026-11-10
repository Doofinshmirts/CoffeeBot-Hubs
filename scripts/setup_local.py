"""Interactive local configuration. Secrets never print or enter the source archive."""
from getpass import getpass
from pathlib import Path
import secrets
from werkzeug.security import generate_password_hash

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    target = ROOT / '.env'
    if target.exists():
        raise SystemExit('.env already exists. Edit it locally; this script will not overwrite it.')
    key = getpass('Supabase secret key (hidden input): ').strip()
    if not key:
        raise SystemExit('A Supabase server secret is required.')
    password = getpass('Choose staff password (12 or more characters): ')
    if len(password) < 12 or password != getpass('Repeat staff password: '):
        raise SystemExit('Passwords must match and contain at least 12 characters.')
    if '\n' in key or '\r' in key:
        raise SystemExit('Invalid key.')
    config = '\n'.join([
        'SUPABASE_URL=https://mbpvfilblwuayldznsev.supabase.co',
        'SUPABASE_SECRET_KEY=' + key,
        'SUPABASE_PUBLISHABLE_KEY=sb_publishable_CM3_mOmJmsUWUteQxezhgA_NtTQjWCA',
        'SECRET_KEY=' + secrets.token_hex(32),
        'APP_URL=http://127.0.0.1:5000',
        'STAFF_USERNAME=driver',
        'STAFF_PASSWORD_HASH=' + generate_password_hash(password),
        'COOKIE_SECURE=false', 'PORT=5000', ''
    ])
    with target.open('x', encoding='utf-8') as output:
        output.write(config)
    print('Saved private .env. Username: driver. Run python app.py to start.')
