from __future__ import annotations

from services.account_service import account_service
from services.openai_backend_api import OpenAIBackendAPI, SEARCH_MODEL

MODEL = SEARCH_MODEL


def handle(body: dict[str, object]) -> dict[str, object]:
    token = account_service.get_text_access_token()
    account = account_service.get_account(token) or {}
    try:
        with OpenAIBackendAPI(token) as backend:
            result = backend.search(str(body["prompt"]))
    except Exception as exc:
        if account_service.is_auth_invalid_error(exc):
            account_service.handle_invalid_token(token, "openai_search", error=str(exc))
        else:
            account_service.handle_request_failure(token, "openai_search", exc)
        raise
    account_service.mark_text_used(token)
    result["_account_email"] = str(account.get("email") or "")
    return result
