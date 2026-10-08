"""Bounded HTTPS Bot API transport without credential-bearing error messages."""
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class BotAPIError(RuntimeError):
    def __init__(self, error_code: int, description: str, retry_after: int | None = None):
        super().__init__(description)
        self.error_code = error_code
        self.retry_after = retry_after


def _http(url: str, payload: dict, timeout: int) -> dict:
    request = Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        try:
            return json.loads(exc.read())
        except (ValueError, UnicodeError):
            return {"ok": False, "error_code": exc.code, "description": "Bot API HTTP failure"}


class BotClient:
    def __init__(self, token: str, *, transport=_http, sleep=time.sleep, attempts: int = 3):
        if not token or type(attempts) is not int or not 1 <= attempts <= 5:
            raise ValueError("invalid bot configuration")
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._attempts = attempts

    def call(self, method: str, payload: dict) -> Any:
        if not method.isalnum() or type(payload) is not dict:
            raise ValueError("invalid Bot API call")
        url = "https://api.telegram.org/bot" + self._token + "/" + method
        for attempt in range(self._attempts):
            try:
                raw = self._transport(url, payload, 45)
            except (OSError, ValueError) as exc:
                error = BotAPIError(0, "Bot API transport failure: " + type(exc).__name__)
            else:
                if type(raw) is not dict or type(raw.get("ok")) is not bool:
                    error = BotAPIError(0, "Malformed Bot API response")
                elif raw["ok"]:
                    if "result" not in raw:
                        raise BotAPIError(0, "Bot API result is missing")
                    return raw["result"]
                else:
                    code = raw.get("error_code", 0)
                    code = code if type(code) is int else 0
                    description = str(raw.get("description", "Bot API failure")).replace(self._token, "[redacted]")
                    retry_after = raw.get("parameters", {}).get("retry_after") if type(raw.get("parameters", {})) is dict else None
                    retry_after = retry_after if type(retry_after) is int and retry_after >= 0 else None
                    error = BotAPIError(code, description, retry_after)
            if error.error_code not in {0, 429} and error.error_code < 500:
                raise error
            if attempt == self._attempts - 1:
                raise error
            self._sleep(min(error.retry_after if error.retry_after is not None else 2 ** attempt, 30))
        raise AssertionError("unreachable")
