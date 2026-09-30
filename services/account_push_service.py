from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlsplit

from curl_cffi import requests


class AccountPushService:
    """Push registered accounts to a compatible remote account service."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._interval_lock = threading.Lock()
        self._settings: dict[str, Any] = {}
        self._last_push_at = 0.0

    def configure(self, settings: dict[str, Any] | None) -> None:
        with self._lock:
            value = settings if isinstance(settings, dict) else {}
            self._settings = {
                "enabled": bool(value.get("enabled", False)),
                "name": str(value.get("name") or "ChatGPT2API服务").strip() or "ChatGPT2API服务",
                "api_url": str(value.get("api_url") or "").strip().rstrip("/"),
                "api_key": str(value.get("api_key") or "").strip(),
                "interval": max(0.0, float(value.get("interval") or 0)),
            }

    def get_public(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._settings)
        has_api_key = bool(result.get("api_key"))
        result["api_key"] = ""
        result["has_api_key"] = has_api_key
        return result

    def _snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._settings)

    def _wait_interval(self, seconds: float) -> None:
        if seconds <= 0:
            return
        with self._interval_lock:
            now = time.monotonic()
            wait_for = max(0.0, self._last_push_at + seconds - now)
            if wait_for:
                time.sleep(wait_for)
            self._last_push_at = time.monotonic()

    @staticmethod
    def _payload(account: dict[str, Any]) -> dict[str, Any]:
        return {
            "accounts": [{
                key: value
                for key, value in account.items()
                if key not in {"push_status", "push_error", "push_at", "push_target"}
            }],
            "refresh": False,
            "return_items": False,
        }

    def push_account(
        self, account: dict[str, Any], *, force: bool = False,
        settings_override: dict[str, Any] | None = None, record_status: bool = True,
    ) -> dict[str, Any]:
        settings = self._snapshot()
        if settings_override is not None:
            settings.update(settings_override)
        target = str(settings.get("name") or settings.get("api_url") or "").strip()
        token = str(account.get("access_token") or "").strip()
        if not token:
            return {"ok": False, "error": "account access_token is missing"}
        if not settings.get("enabled") and not force:
            return {"ok": False, "skipped": True, "error": "push service is disabled"}
        api_url = str(settings.get("api_url") or "").strip()
        api_key = str(settings.get("api_key") or "").strip()
        if not api_url or not api_key:
            return {"ok": False, "target": target, "error": "push service api_url/api_key is not configured"}
        parsed = urlsplit(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            return {"ok": False, "target": target, "error": "push service api_url must be an http(s) base URL"}
        endpoint = urljoin(f"{api_url}/", "api/accounts")
        now = datetime.now(timezone.utc).isoformat()
        status_code: int | None = None
        try:
            self._wait_interval(float(settings.get("interval") or 0))
            response = requests.post(
                endpoint,
                json=self._payload(account),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                timeout=30,
                allow_redirects=False,
            )
            status_code = int(response.status_code)
            if not 200 <= status_code < 300:
                detail = str(getattr(response, "text", "") or "")[:500]
                raise RuntimeError(f"remote push HTTP {status_code}: {detail}")
            try:
                body = response.json()
            except Exception as exc:
                raise RuntimeError("remote push returned invalid JSON") from exc
            if not isinstance(body, dict):
                raise RuntimeError("remote push returned invalid response")
            if body.get("errors"):
                raise RuntimeError(f"remote push errors: {str(body['errors'])[:400]}")
            if int(body.get("added") or 0) + int(body.get("skipped") or 0) < 1:
                raise RuntimeError("remote push did not confirm account import")
            result = {"ok": True, "status_code": status_code, "target": target}
            if record_status:
                from services.account_service import account_service
                account_service.update_account(token, {
                    "push_status": "success", "push_error": None,
                    "push_at": now, "push_target": target,
                }, quiet=True)
            return result
        except Exception as exc:
            error = str(exc)[:500]
            if record_status:
                try:
                    from services.account_service import account_service
                    account_service.update_account(token, {
                        "push_status": "failed", "push_error": error,
                        "push_at": now, "push_target": target,
                    }, quiet=True)
                except Exception:
                    pass
            return {"ok": False, "error": error, "target": target,
                    **({"status_code": status_code} if status_code is not None else {})}


account_push_service = AccountPushService()
