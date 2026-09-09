"""Plan NFR-2 — every credential is encrypted before it reaches the database."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.exceptions.errors import ValidationException

_DEV_SEED = "agent-platform-dev-only-key"


def _fernet() -> Fernet:
    raw = settings.CREDENTIAL_KEY or _DEV_SEED
    # Accept a real Fernet key as-is; otherwise derive one so dev needs no setup.
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValidationException("Credential could not be decrypted") from exc


def using_dev_key() -> bool:
    return not settings.CREDENTIAL_KEY
