import asyncio
import logging
import ssl
from typing import Any

import aiohttp

from app.config import Settings

logger = logging.getLogger(__name__)


class MaxClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = settings.max_api_base_url.rstrip("/")

    def _ssl_parameter(self) -> ssl.SSLContext | bool:
        if self.settings.max_ssl_verify:
            return True
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        return ssl_context

    async def send_message_to_user(
        self,
        user_id: int,
        text: str,
        retries: int = 3,
        format: str | None = "markdown",
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        return await self._post_messages(
            text=text,
            user_id=user_id,
            retries=retries,
            format=format,
            attachments=attachments,
        )

    async def send_message_to_chat(
        self,
        chat_id: int,
        text: str,
        retries: int = 3,
        format: str | None = "markdown",
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        return await self._post_messages(
            text=text,
            chat_id=chat_id,
            retries=retries,
            format=format,
            attachments=attachments,
        )

    async def subscribe_webhook(self, webhook_url: str) -> bool:
        payload = {
            "url": webhook_url,
            "update_types": ["message_created", "bot_added", "message_callback"],
        }
        success, _retryable = await self._request("POST", "/subscriptions", json_body=payload)
        return success

    async def _post_messages(
        self,
        text: str,
        retries: int,
        user_id: int | None = None,
        chat_id: int | None = None,
        format: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        if chat_id is not None:
            params["chat_id"] = chat_id

        payload: dict[str, Any] = {"text": text}
        if format:
            payload["format"] = format
        if attachments is not None:
            payload["attachments"] = attachments

        for attempt in range(retries):
            success, retryable = await self._request(
                "POST",
                "/messages",
                json_body=payload,
                params=params,
            )
            if success:
                return True
            if not retryable:
                return False
            await asyncio.sleep(2**attempt)
        return False

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[bool, bool]:
        if not self.settings.max_bot_token:
            logger.warning("MAX_BOT_TOKEN is not set")
            return False, False

        headers = {"Authorization": self.settings.max_bot_token}
        url = f"{self.base_url}{path}"

        try:
            connector = aiohttp.TCPConnector(ssl=self._ssl_parameter())
            async with aiohttp.ClientSession(connector=connector) as session:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    if response.status >= 400:
                        body = await response.text()
                        logger.error("MAX API error %s %s: %s", method, path, body)
                        retryable = response.status >= 500
                        return False, retryable
                    return True, False
        except aiohttp.ClientError:
            logger.exception("MAX API request failed: %s %s", method, path)
            return False, True
