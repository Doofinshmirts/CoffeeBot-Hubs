"""Create a confirmed driver account without storing credentials in source control."""
from getpass import getpass
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

load_dotenv(Path(__file__).resolve().parent.parent / '.env', interpolate=False)


def main():
    url = os.environ.get('SUPABASE_URL', '')
    secret = os.environ.get('SUPABASE_SECRET_KEY', '')
    if not url or not secret:
        raise SystemExit('Set SUPABASE_URL and SUPABASE_SECRET_KEY in the ignored .env first.')
    email = input('Driver email: ').strip().lower()
    full_name = input('Driver name: ').strip()
    phone = input('Driver phone: ').strip()
    password = getpass('Driver password (at least 12 characters): ')
    if len(password) < 12:
        raise SystemExit('Password must have at least 12 characters.')

    client = create_client(url, secret)
    response = client.auth.admin.create_user({
        'email': email,
        'password': password,
        'email_confirm': True,
        'user_metadata': {
            'account_type': 'individual',
            'full_name': full_name,
            'phone': phone,
        },
    })
    client.table('profiles').update({'role': 'driver'}).eq('id', str(response.user.id)).execute()
    print('Confirmed driver account created. The password was not written to disk.')


if __name__ == '__main__':
    main()
