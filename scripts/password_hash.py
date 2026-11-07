"""Generate a staff password hash without displaying the password."""
from getpass import getpass
from werkzeug.security import generate_password_hash

if __name__ == '__main__':
    value = getpass('Choose staff password (at least 12 characters): ')
    if len(value) < 12:
        raise SystemExit('Use at least 12 characters.')
    if value != getpass('Repeat staff password: '):
        raise SystemExit('Passwords did not match.')
    print(generate_password_hash(value))
