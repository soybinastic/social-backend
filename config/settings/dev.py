"""Local development settings."""

from .base import *  # noqa: F403
from .base import env

DEBUG = env.bool("DJANGO_DEBUG", default=True)
ALLOWED_HOSTS = ["*"]

# Serve locally stored uploads through Django while developing.
CORS_ALLOW_ALL_ORIGINS = True
WEBSOCKET_ALLOWED_ORIGINS = ["*"]
