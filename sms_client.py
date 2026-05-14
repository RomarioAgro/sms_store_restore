import os
import ssl
import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError


@dataclass(frozen=True)
class Message:
    message_id: int
    chat_id: str
    text: str
    created_at: str


@dataclass(frozen=True)
class DeleteResult:
    message: Message | None
    deleted: int


class SmsClientError(Exception):
    pass


class SmsClientHTTPError(SmsClientError):
    def __init__(self, status_code: int, body: str) -> None:
        super().__init__(f"HTTP {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class SmsClientNetworkError(SmsClientError):
    pass


class SmsStoreClient:
    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.base_url = (base_url or os.getenv("BASE_URL", "https://127.0.0.1:8000")).rstrip("/")
        self.token = token or os.getenv("TOKEN", "")
        ca_certfile = os.getenv("SSL_CA_CERTFILE") or os.getenv("CA_CERT_FILE")
        self.ssl_context = ssl.create_default_context(cafile=ca_certfile) if ca_certfile else None
        if not self.token:
            raise ValueError("TOKEN is required: pass token or set the TOKEN environment variable")
        self.logger = logger or logging.getLogger(__name__)

    def _request(self, method: str, path: str, payload: dict | None = None) -> Any:
        url = f"{self.base_url}{path}"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = None

        self.logger.info("request start method=%s url=%s", method, url)

        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.ssl_context) as response:
                body = response.read().decode("utf-8")
                self.logger.info("request done method=%s url=%s status=%s", method, url, response.status)
                return json.loads(body) if body else None
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            self.logger.error(
                "http error method=%s url=%s status=%s body=%s",
                method,
                url,
                exc.code,
                body,
            )
            raise SmsClientHTTPError(exc.code, body) from exc
        except URLError as exc:
            self.logger.error("network error method=%s url=%s error=%s", method, url, exc)
            raise SmsClientNetworkError(str(exc)) from exc

    def get_last_message_by_chat_id(self, chat_id: str) -> Message | None:
        query = urllib.parse.urlencode({"chat_id": chat_id})
        items = self._request("GET", f"/messages?{query}")

        if not items:
            return None

        last_item = items[-1]
        return Message(
            message_id=last_item["message_id"],
            chat_id=last_item["chat_id"],
            text=last_item["text"],
            created_at=last_item["created_at"],
        )

    def delete_message_by_id(self, message_id: int) -> int:
        query = urllib.parse.urlencode({"message_id": message_id})
        result = self._request("DELETE", f"/messages?{query}")
        return int(result["deleted"])

    def delete_last_message_by_chat_id(self, chat_id: str) -> DeleteResult:
        message = self.get_last_message_by_chat_id(chat_id)
        if message is None:
            return DeleteResult(message=None, deleted=0)

        deleted = self.delete_message_by_id(message.message_id)
        return DeleteResult(message=message, deleted=deleted)
