from __future__ import annotations

from threading import Lock


class SecretStore:
    """Write-only-from-API secret storage with an in-memory fallback."""

    service_name = "双图生图工作台"

    def __init__(self) -> None:
        self._session: dict[str, str] = {}
        self._lock = Lock()

    def set(self, profile_id: str, secret: str, remember: bool) -> bool:
        with self._lock:
            self._session[profile_id] = secret
        if not remember:
            return False
        try:
            import keyring

            keyring.set_password(self.service_name, profile_id, secret)
            return True
        except Exception:
            return False

    def get(self, profile_id: str) -> str | None:
        with self._lock:
            session_secret = self._session.get(profile_id)
        if session_secret:
            return session_secret
        try:
            import keyring

            return keyring.get_password(self.service_name, profile_id)
        except Exception:
            return None

    def clear(self, profile_id: str) -> None:
        with self._lock:
            self._session.pop(profile_id, None)
        try:
            import keyring

            keyring.delete_password(self.service_name, profile_id)
        except Exception:
            pass

