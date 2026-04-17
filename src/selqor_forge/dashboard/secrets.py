# Copyright (c) Selqor Labs.
# SPDX-License-Identifier: Apache-2.0

"""Secret encryption, masking, and round-trip helpers for dashboard state."""

from __future__ import annotations

import json
import logging
import os
import stat
from pathlib import Path
from typing import Any, cast

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

_STATE_KEY_FILENAME = ".forge-secret.key"
_ENCRYPTED_PREFIX = "forge$fernet$"
_SECRET_NAME_TOKENS = ("api_key", "token", "secret", "password", "authorization", "cookie")
_NON_SECRET_NAME_TOKENS = (
    "token_url",
    "oauth_token_url",
    "token_response_path",
    "token_expiry_path",
    "token_expiry_seconds",
    "token_request_method",
    "auth_header_name",
    "auth_header_prefix",
)


class DashboardSecretManager:
    """Encrypt and decrypt dashboard secrets with a single Fernet key."""

    def __init__(
        self,
        key: bytes,
        *,
        source: str,
        auto_generated_this_run: bool,
        key_path: Path | None = None,
    ) -> None:
        self._fernet = Fernet(key)
        self.source = source
        self.auto_generated_this_run = auto_generated_this_run
        self.key_path = key_path

    @classmethod
    def from_environment(cls, state_dir: Path) -> "DashboardSecretManager":
        """Load the dashboard secret key from env or the state directory."""
        env_key = os.environ.get("FORGE_SECRET_KEY", "").strip()
        if env_key:
            key = cls._parse_key(env_key)
            return cls(key, source="env", auto_generated_this_run=False)

        state_dir.mkdir(parents=True, exist_ok=True)
        key_path = state_dir / _STATE_KEY_FILENAME
        if key_path.is_file():
            key = cls._parse_key(key_path.read_text(encoding="utf-8").strip())
            return cls(
                key,
                source="state-dir",
                auto_generated_this_run=False,
                key_path=key_path,
            )

        generated = Fernet.generate_key()
        key_path.write_text(generated.decode("utf-8"), encoding="utf-8")
        try:
            os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.debug("Could not tighten permissions on %s", key_path, exc_info=True)
        logger.warning(
            "FORGE_SECRET_KEY is not set; generated a local dashboard key at %s. "
            "Persist FORGE_SECRET_KEY before exposing the dashboard anywhere outside local development.",
            key_path,
        )
        return cls(
            generated,
            source="state-dir-auto-generated",
            auto_generated_this_run=True,
            key_path=key_path,
        )

    @staticmethod
    def _parse_key(raw: str) -> bytes:
        key = raw.encode("utf-8")
        try:
            Fernet(key)
        except (ValueError, TypeError) as exc:
            raise RuntimeError(
                "FORGE_SECRET_KEY must be a valid Fernet key. "
                "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc
        return key

    @staticmethod
    def is_encrypted(value: Any) -> bool:
        return isinstance(value, str) and value.startswith(_ENCRYPTED_PREFIX)

    def encrypt_text(self, value: str | None) -> str | None:
        """Encrypt a secret string, leaving legacy encrypted values untouched."""
        if value is None:
            return None
        if self.is_encrypted(value):
            return value
        if value == "":
            return ""
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{_ENCRYPTED_PREFIX}{token}"

    def decrypt_text(self, value: str | None) -> str | None:
        """Decrypt a secret string, falling back to legacy plaintext rows."""
        if value is None:
            return None
        if not self.is_encrypted(value):
            return value
        token = value[len(_ENCRYPTED_PREFIX) :]
        try:
            decrypted = self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
            return cast(str, decrypted)
        except InvalidToken:
            logger.warning("Could not decrypt dashboard secret; keeping stored placeholder value")
            return None

    def encrypt_json_blob(self, value: Any) -> str | None:
        """Encrypt an arbitrary JSON-serialisable object as a single blob."""
        if value is None:
            return None
        if isinstance(value, str) and self.is_encrypted(value):
            return value
        return self.encrypt_text(json.dumps(value))

    def decrypt_json_blob(self, value: Any, default: Any) -> Any:
        """Decrypt a JSON blob, or decode legacy plaintext JSON when needed."""
        if value in (None, ""):
            return default
        if isinstance(value, (dict, list)):
            return value
        if not isinstance(value, str):
            return default

        decoded = self.decrypt_text(value)
        if decoded in (None, ""):
            decoded = value if not self.is_encrypted(value) else None
        if decoded in (None, ""):
            return default
        try:
            return json.loads(cast(str, decoded))
        except (TypeError, ValueError):
            return default


def is_secret_name(name: str | None) -> bool:
    """Return *True* for field names that should be masked/encrypted."""
    if not name:
        return False
    normalized = name.strip().lower().replace("-", "_")
    if not normalized:
        return False
    if any(token in normalized for token in _NON_SECRET_NAME_TOKENS):
        return False
    return any(token in normalized for token in _SECRET_NAME_TOKENS)


def mask_secret(value: str | None) -> str | None:
    """Mask a secret while preserving enough shape for the UI to show state."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None

    prefix = ""
    separators = [idx for idx in (stripped.find("_"), stripped.find("-")) if idx > 0]
    if separators:
        cut = min(separators)
        next_cut = stripped.find(stripped[cut], cut + 1)
        if next_cut > 0:
            prefix = stripped[: next_cut + 1]
        else:
            prefix = stripped[: cut + 1]
    elif len(stripped) > 8:
        prefix = stripped[:2]

    suffix = stripped[-4:] if len(stripped) > 4 else ""
    return f"{prefix}{'•' * 4}{suffix}"


def mask_named_value(name: str, value: Any) -> Any:
    """Mask a value when its field name indicates secret material."""
    if is_secret_name(name) and isinstance(value, str):
        return mask_secret(value)
    return mask_nested_secrets(value)


def mask_nested_secrets(value: Any) -> Any:
    """Mask secrets inside nested dict/list payloads."""
    if isinstance(value, dict):
        return {key: mask_named_value(key, item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_nested_secrets(item) for item in value]
    return value


def restore_masked_value(new_value: Any, old_value: Any, field_name: str | None = None) -> Any:
    """Preserve the existing secret when a masked UI value is posted back unchanged."""
    if isinstance(new_value, str) and isinstance(old_value, str):
        masked_old = mask_secret(old_value) if (field_name is None or is_secret_name(field_name)) else None
        if masked_old and new_value == masked_old:
            return old_value
        return new_value

    if isinstance(new_value, dict) and isinstance(old_value, dict):
        restored: dict[str, Any] = {}
        for key, item in new_value.items():
            restored[key] = restore_masked_value(item, old_value.get(key), key)
        return restored

    if isinstance(new_value, list) and isinstance(old_value, list):
        restored_list: list[Any] = []
        for index, item in enumerate(new_value):
            previous = old_value[index] if index < len(old_value) else None
            restored_list.append(restore_masked_value(item, previous, field_name))
        return restored_list

    return new_value
