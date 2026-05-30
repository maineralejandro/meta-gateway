import hashlib
import os
from pathlib import Path
from typing import Any

import httpx
import structlog
from dotenv import dotenv_values

from core.config import settings

logger = structlog.get_logger()

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:8]


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
                token_fingerprint=_token_fingerprint(current_token) if current_token else "EMPTY",
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

    async def send_interactive_buttons(
        self,
        phone: str,
        body_text: str,
        buttons: list[dict[str, str]],
    ) -> dict[str, Any]:
        if len(buttons) > 3:
            logger.warning("interactive_buttons_truncated", count=len(buttons), max=3)
            buttons = buttons[:3]
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {
                    "buttons": [
                        {
                            "type": "reply",
                            "reply": {"id": b["id"], "title": b["title"]},
                        }
                        for b in buttons
                    ]
                },
            },
        }
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result: dict[str, Any] = resp.json()
        return result

    async def send_interactive_list(
        self,
        phone: str,
        body_text: str,
        button_text: str,
        sections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_rows = sum(len(s.get("rows", [])) for s in sections)
        if total_rows > 10:
            logger.warning("interactive_list_truncated", total_rows=total_rows, max=10)
        payload = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": button_text,
                    "sections": sections,
                },
            },
        }
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result2: dict[str, Any] = resp.json()
        return result2

    async def send_image(
        self,
        phone: str,
        image_url: str,
        caption: str = "",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "image",
            "image": {"url": image_url},
        }
        if caption:
            payload["image"]["caption"] = caption
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result_img: dict[str, Any] = resp.json()
        return result_img

    async def send_template(
        self,
        phone: str,
        template_name: str,
        language: str = "es",
        components: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": phone,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }
        if components:
            payload["template"]["components"] = components
        client = await self._get_client()
        resp = await client.post(f"{self.base_url}/messages", json=payload)
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result3: dict[str, Any] = resp.json()
        return result3

    async def create_template(self, waba_id: str, template_data: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post(
            f"{settings.META_API_URL}/{waba_id}/message_templates",
            json=template_data,
        )
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result4: dict[str, Any] = resp.json()
        return result4

    async def delete_template(self, waba_id: str, template_name: str) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.delete(
            f"{settings.META_API_URL}/{waba_id}/message_templates",
            params={"name": template_name},
        )
        if resp.status_code >= 400:
            error_body = resp.text
            self._log_auth_error(resp.status_code, error_body)
            return {"error": True, "status": resp.status_code, "detail": error_body}
        result5: dict[str, Any] = resp.json()
        return result5

    async def get_templates(self, waba_id: str) -> list[dict[str, Any]]:
        client = await self._get_client()
        all_templates: list[dict[str, Any]] = []
        url = f"{settings.META_API_URL}/{waba_id}/message_templates"
        while url:
            resp = await client.get(url)
            if resp.status_code >= 400:
                error_body = resp.text
                self._log_auth_error(resp.status_code, error_body)
                return []
            data = resp.json()
            all_templates.extend(data.get("data", []))
            url = data.get("paging", {}).get("next")
        return all_templates

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
            token_health = await self.check_token_health()
            if token_health.get("valid"):
                return {"connected": True, "status_code": 200, "error": None, **token_health}
            return {"connected": False, "status_code": None, "error": token_health.get("error", "Token invalid"), **token_health}
        except Exception as e:
            logger.error("meta_health_check_exception", error=str(e))
            return {"connected": False, "status_code": None, "error": str(e)}

    async def check_token_health(self) -> dict[str, Any]:
        token = self._resolve_token()
        if not token:
            logger.error("meta_token_missing")
            return {"valid": False, "error": "No WHATSAPP_ACCESS_TOKEN found"}
        try:
            is_valid = False
            expires_at: int | None = None
            token_type = "unknown"
            scopes: list[str] = []
            error_msg = "unknown"
            error_subcode = None

            app_access_token: str | None = None
            if settings.META_APP_ID and settings.META_APP_SECRET:
                app_access_token = f"{settings.META_APP_ID}|{settings.META_APP_SECRET}"

            if app_access_token:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    headers={"Authorization": f"Bearer {app_access_token}"},
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

                    if not is_valid:
                        error_msg = data.get("error", {}).get("message", "unknown")
                        error_subcode = resp.json().get("error", {}).get("error_subcode", data.get("error", {}).get("code"))
                    logger.error(
                        "meta_token_invalid",
                        token_fingerprint=_token_fingerprint(token),
                        error=error_msg,
                        error_subcode=error_subcode,
                        hint="Update WHATSAPP_ACCESS_TOKEN in .env or set env var",
                    )
            else:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    headers={"Authorization": f"Bearer {token}"},
                ) as client:
                    resp = await client.get(f"{settings.META_API_URL}/me/permissions")
                    if resp.status_code == 200:
                        is_valid = True
                        token_type = "SYSTEM_USER"
                        expires_at = 0
                        perms = resp.json().get("data", [])
                        scopes = [p["permission"] for p in perms if p.get("status") == "active"]
                    else:
                        is_valid = False
                        token_type = "unknown"
                        expires_at = None
                        scopes = []
                    logger.error(
                        "meta_token_invalid",
                        token_fingerprint=_token_fingerprint(token),
                        status_code=resp.status_code,
                        hint="Token verification failed. Set META_APP_ID and META_APP_SECRET for /debug_token support",
                    )

            from datetime import UTC, datetime
            remaining_min: float | None = None
            if expires_at and expires_at > 0:
                remaining_min = (datetime.fromtimestamp(expires_at, tz=UTC) - datetime.now(tz=UTC)).total_seconds() / 60

            self._token_expires_at = expires_at

            if is_valid:
                logger.info(
                    "meta_token_valid",
                    token_fingerprint=_token_fingerprint(token),
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

    async def retrieve_media_url(self, media_id: str) -> str | None:
        try:
            client = await self._get_client()
            resp = await client.get(f"{settings.META_API_URL}/{media_id}")
            if resp.status_code >= 400:
                logger.error("meta_media_retrieve_failed", media_id=media_id, status=resp.status_code)
                return None
            data = resp.json()
            url = data.get("url")
            if isinstance(url, str):
                return url
            return None
        except Exception as e:
            logger.error("meta_media_retrieve_error", media_id=media_id, error=str(e))
            return None

    async def download_media(self, media_url: str) -> tuple[bytes, str] | None:
        try:
            client = await self._get_client()
            resp = await client.get(media_url)
            if resp.status_code >= 400:
                logger.error("meta_media_download_failed", status=resp.status_code)
                return None
            content_type = resp.headers.get("content-type", "application/octet-stream")
            return resp.content, content_type
        except Exception as e:
            logger.error("meta_media_download_error", error=str(e))
            return None

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


meta_client = MetaAPIClient()
