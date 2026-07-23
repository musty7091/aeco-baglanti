from __future__ import annotations

import os
import secrets
from pathlib import Path

from django.conf import settings

TOKEN_FILE = Path(settings.BASE_DIR) / 'runtime' / 'scanner_token.txt'


def get_scanner_token() -> str:
    """Django ve yerel tarama servisinin paylaştığı, dosyada saklanan token."""
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding='utf-8').strip()
        if len(token) >= 32:
            return token
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding='utf-8')
    try:
        os.chmod(TOKEN_FILE, 0o600)
    except OSError:
        pass
    return token


def scanner_client_config() -> dict[str, str]:
    return {
        'service_url': settings.SCANNER_SERVICE_URL.rstrip('/'),
        'token': get_scanner_token(),
    }
