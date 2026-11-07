"""Explicit, local-only fixture server for browser QA; not the submitted cloud demo."""
from coffeebot import create_app
from werkzeug.security import generate_password_hash
from tests.fakes import MemoryRepository

app = create_app({'SECRET_KEY':'local-fixture-only', 'STAFF_PASSWORD_HASH':generate_password_hash('test-password-123'),
                  'SESSION_COOKIE_SECURE':False}, MemoryRepository())

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5055, debug=False, use_reloader=False)
