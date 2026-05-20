import os
from pathlib import Path
from typing import Any

import httpx
import structlog
from dotenv import dotenv_values

from core.config import settings

logger = structlog.get_logger()

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


class MetaAPIClient:
    def __init__(self) -> None:
        self.base_url = f"{settings.META_API_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
        self._client: httpx.AsyncClient | None = None
        self._cached_token: str | None = None
        self._token_expires_at: int | None = None

    def _resolve_token(self) -> str:
        try:
            fresh = dotenv_values(_ENV_PATH)
            token = fresh.get("WHATSAPP_ACCESS_TOKEN")
            if token:
                return token
        except Exception:
            pass
        env_token = os.environ.get("WHATSAPP_ACCESS_TOKEN")
        if env_token:
            return env_token
        return settings.WHATSAPP_ACCESS_TOKEN

    def _build_headers(self, token: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _get_client(self) -> httpx.AsyncClient:
        current_token = self._resolve_token()
        if (
            self._client is None
            or self._client.is_closed
            or self._cached_token != current_token
        ):
            if self._client and not self._client.is_closed:
                await self._client.aclose()
            logger.info(
                "meta_token_refreshed",
                token_prefix=current_token[:10] if current_token else "EMPTY",
                token_length=len(current_token),
            )
            self._cached_token = current_token
            self._client = httpx.AsyncClient(
                headers=self._build_headers(current_token),
                timeout=30.0,
            )
        return self._client

    async def send_text(self, phone: str, text: str) -> dict[str, Any]:
        client = await self._get_client()
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "text",
            "text": {"body": text},
        }
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result: dict[str, Any] = resp.json()
        return result

    async def send_message(self, phone: str, text: str) -> dict[str, Any]:
        return await self.send_text(phone, text)

    async def mark_read(self, message_id: str) -> dict[str, Any]:
        client = await self._get_client()
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result: dict[str, Any] = resp.json()
        return result

    async def mark_read_with_typing(self, message_id: str) -> dict[str, Any]:
        client = await self._get_client()
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
            "typing_indicator": {"type": "text"},
        }
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result: dict[str, Any] = resp.json()
        return result

    async def health_check(self) -> dict[str, Any]:
        try:
            if not settings.WHATSAPP_ACCESS_TOKEN:
                return {"connected": False, "status_code": None, "error": "No access token configured"}
            client = await self._get_client()
            resp = await client.get(self.base_url)
            if resp.status_code == 200:
                return {"connected": True, "status_code": 200, "error": None}
            error_msg = resp.text[:200]
            self._log_auth_error(resp.status_code, error_msg)
            return {"connected": False, "status_code": resp.status_code, "error": error_msg}
        except Exception as e:
            logger.error("meta_health_check_exception", error=str(e))
            return {"connected": False, "status_code": None, "error": str(e)}

    async def check_token_health(self) -> dict[str, Any]:
        token = self._resolve_token()
        if not token:
            logger.error("meta_token_missing")
            return {"valid": False, "error": "No WHATSAPP_ACCESS_TOKEN found"}
        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                headers={"Authorization": f"Bearer {token}"},
            ) as client:
                resp = await client.get(
                    f"{settings.META_API_URL}/debug_token",
                    params={"input_token": token},
                )
            data = resp.json().get("data", {})
            is_valid = data.get("is_valid", False)
            expires_at = data.get("expires_at")
            token_type = data.get("type", "unknown")
            scopes = data.get("scopes", [])

            from datetime import UTC, datetime
            remaining_min = None
            if expires_at:
                remaining_min = (datetime.fromtimestamp(expires_at, tz=UTC) - datetime.now(tz=UTC)).total_seconds() / 60

            self._token_expires_at = expires_at

            if is_valid:
                logger.info(
                    "meta_token_valid",
                    token_prefix=token[:10],
                    token_type=token_type,
                    expires_at=expires_at,
                    remaining_min=round(remaining_min or 0),
                    scopes=",".join(scopes[:5]),
                )
                if remaining_min is not None and remaining_min < 60:
                    logger.warning(
                        "meta_token_expiring_soon",
                        remaining_min=round(remaining_min),
                        hint="Generate a System User token for permanent access",
                    )
            else:
                error_msg = data.get("error", {}).get("message", "unknown")
                error_subcode = resp.json().get("error", {}).get("error_subcode", data.get("error", {}).get("code"))
                logger.error(
                    "meta_token_invalid",
                    token_prefix=token[:10],
                    error=error_msg,
                    error_subcode=error_subcode,
                    hint="Update WHATSAPP_ACCESS_TOKEN in .env or set env var",
                )

            return {
                "valid": is_valid,
                "type": token_type,
                "expires_at": expires_at,
                "remaining_min": round(remaining_min) if remaining_min else None,
                "scopes": scopes,
            }
        except Exception as e:
            logger.error("meta_token_health_check_failed", error=str(e))
            return {"valid": False, "error": str(e)}

    def _log_auth_error(self, status_code: int, body: str) -> None:
        try:
            error_data = __import__("json").loads(body)
            err = error_data.get("error", {})
            code = err.get("code")
            subcode = err.get("error_subcode")
        except Exception:
            code = None
            subcode = None

        if code == 190 and subcode == 463:
            logger.error(
                "meta_token_expired",
                status=status_code,
                hint="Temporary token expired. Update WHATSAPP_ACCESS_TOKEN in .env or create a System User token at https://business.facebook.com/settings/system-users",
            )
        elif code == 190:
            logger.error(
                "meta_auth_error",
                status=status_code,
                error_subcode=subcode,
                hint="Token may be invalid or revoked. Check WHATSAPP_ACCESS_TOKEN in .env",
            )
        else:
            logger.error("meta_api_error", status=status_code, body=body[:300])

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


meta_client = MetaAPIClient()
