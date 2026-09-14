"""Encrypted token vault. Secrets (API keys, PATs) never touch the DB or logs.

Encryption: Fernet (AES-128-CBC + HMAC) with a locally generated key file
stored at ~/.smm/vault.key with 0600 permissions. For cloud mode, swap this
for a KMS-backed implementation behind the same get/set/delete interface.
"""
import json
import os

from cryptography.fernet import Fernet

from app.config.settings import vault_key_path, vault_path


def _get_fernet() -> Fernet:
    key_path = vault_key_path()
    if not key_path.exists():
        key = Fernet.generate_key()
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
    return Fernet(key_path.read_bytes())


def _load() -> dict:
    if not vault_path().exists():
        return {}
    data = _get_fernet().decrypt(vault_path().read_bytes())
    return json.loads(data)


def _save(vault: dict) -> None:
    token = _get_fernet().encrypt(json.dumps(vault).encode())
    vault_path().write_bytes(token)
    os.chmod(vault_path(), 0o600)


def set_secret(provider: str, secrets: dict) -> None:
    vault = _load()
    vault[provider] = secrets
    _save(vault)


def get_secret(provider: str) -> dict | None:
    return _load().get(provider)


def delete_secret(provider: str) -> None:
    vault = _load()
    if provider in vault:
        del vault[provider]
        _save(vault)
