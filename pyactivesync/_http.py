"""Thin HTTP transport for EAS: one ``requests.Session``, auth + headers + retries."""
from __future__ import annotations

import time

import requests

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_RETRY_TOTAL = 3
_RETRY_BACKOFF_FACTOR = 0.5
_EAS_PROTOCOL_VERSION = "16.1"


class Transport:
    """POSTs WBXML bodies to ``/Microsoft-Server-ActiveSync`` and returns raw response bytes."""

    def __init__(
        self,
        server: str,
        username: str,
        password: str,
        *,
        device_id: str,
        device_type: str = "pyactivesync",
        user_agent: str = "pyactivesync/0.1",
        verify_ssl: bool = True,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = f"https://{server}/Microsoft-Server-ActiveSync"
        self.device_id = device_id
        self.device_type = device_type
        self.timeout = timeout
        self.policy_key: str | None = None

        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_ssl
        self.session.headers["User-Agent"] = user_agent

    def post(
        self,
        cmd: str,
        user: str,
        wbxml: bytes,
        *,
        extra_params: dict[str, str] | None = None,
        timeout: float | None = None,
        idempotent: bool = False,
    ) -> bytes:
        """POST one command. ``idempotent`` must only be set for commands with no
        side effect that could be duplicated by a blind resend (e.g. ``Sync``,
        ``FolderSync``, ``ItemOperations`` Fetch) -- a 5xx can happen *after* the
        server already durably processed a mutating command (``SendMail``,
        ``FolderCreate``, ``MoveItems``, a ``Settings`` Set, ...), and retrying
        those would resend the identical body and risk duplicating the effect.
        """
        params = {
            "Cmd": cmd,
            "User": user,
            "DeviceId": self.device_id,
            "DeviceType": self.device_type,
        }
        if extra_params:
            params.update(extra_params)
        headers = {
            "Content-Type": "application/vnd.ms-sync.wbxml",
            "MS-ASProtocolVersion": _EAS_PROTOCOL_VERSION,
        }
        if self.policy_key:
            headers["X-MS-PolicyKey"] = self.policy_key
        effective_timeout = timeout if timeout is not None else self.timeout

        attempts = _RETRY_TOTAL + 1 if idempotent else 1
        for attempt in range(attempts):
            resp = self.session.post(
                self.base_url,
                params=params,
                data=wbxml,
                headers=headers,
                timeout=effective_timeout,
            )
            if resp.status_code in _RETRYABLE_STATUS and attempt < attempts - 1:
                time.sleep(_RETRY_BACKOFF_FACTOR * (2**attempt))
                continue
            resp.raise_for_status()
            return resp.content
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.session.close()
