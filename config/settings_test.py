"""Einstellungen für die automatischen Tests."""

import os
import tempfile

os.environ.setdefault("FV_DEBUG", "1")

from .settings import *  # noqa: E402,F403

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
PRIVATE_MEDIA_ROOT = tempfile.mkdtemp(prefix="fv-test-")
