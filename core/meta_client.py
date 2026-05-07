from typing import Any

import httpx
import structlog

from core.config import settings

logger = structlog.get_logger()


class MetaAPIClient:
    def __init__(self) -> None:
        self.base_url = f"{settings.META_API_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}"
        self.headers = {
            "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers=self.headers,
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
            logger.error("meta_api_error", status=resp.status_code, body=error_body)
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
            logger.error("meta_mark_read_error", status=resp.status_code, body=error_body)
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
            logger.error("meta_mark_read_typing_error", status=resp.status_code, body=error_body)
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
            logger.warning("meta_health_check_failed", status=resp.status_code, body=error_msg)
            return {"connected": False, "status_code": resp.status_code, "error": error_msg}
        except Exception as e:
            logger.error("meta_health_check_exception", error=str(e))
            return {"connected": False, "status_code": None, "error": str(e)}

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


meta_client = MetaAPIClient()
