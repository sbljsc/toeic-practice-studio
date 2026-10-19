"""Production entrypoint: builds the app from config with the real clock."""
from .app import create_app

app = create_app()
