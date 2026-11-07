"""WSGI entry point; waitress provides a Windows-compatible local server."""
import os
from coffeebot import create_app

app = create_app()

if __name__ == '__main__':
    from waitress import serve
    serve(app, host='127.0.0.1', port=int(os.environ.get('PORT', 5000)))
