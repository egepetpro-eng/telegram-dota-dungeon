import json

import pytest


def test_api_uses_json_post_and_returns_parsed_result():
    from dota_dungeon.telegram.client import BotClient
    captured = []

    def transport(url, payload, timeout):
        captured.append((url.rsplit("/", 1)[1], payload, timeout))
        return {"ok": True, "result": {"message_id": 9}}

    result = BotClient("dummy", transport=transport).call("sendMessage", {"chat_id": 11, "text": "hello"})
    assert result == {"message_id": 9}
    assert captured[0][:2] == ("sendMessage", {"chat_id": 11, "text": "hello"})


def test_rate_limit_waits_then_completes_real_response_parsing():
    from dota_dungeon.telegram.client import BotClient
    responses = iter([{"ok": False, "error_code": 429, "description": "wait", "parameters": {"retry_after": 2}},
                      {"ok": True, "result": [{"update_id": 123}]}])
    waits = []
    result = BotClient("dummy", transport=lambda *args: next(responses), sleep=waits.append).call("getUpdates", {})
    assert result == [{"update_id": 123}]
    assert waits == [2]


def test_permanent_error_is_redacted_and_never_retried():
    from dota_dungeon.telegram.client import BotAPIError, BotClient
    responses = iter([{"ok": False, "error_code": 403, "description": "blocked private secret-token"}])
    with pytest.raises(BotAPIError) as error:
        BotClient("secret-token", transport=lambda *args: next(responses)).call("sendMessage", {})
    assert error.value.error_code == 403
    assert "secret-token" not in str(error.value)


def test_retries_are_bounded_and_network_error_does_not_expose_token():
    from dota_dungeon.telegram.client import BotAPIError, BotClient
    attempts = []

    def transport(*args):
        attempts.append(1)
        raise OSError("https://api.telegram.org/botsecret-token/sendMessage")

    with pytest.raises(BotAPIError) as error:
        BotClient("secret-token", transport=transport, sleep=lambda seconds: None, attempts=3).call("sendMessage", {})
    assert len(attempts) == 3
    assert "secret-token" not in str(error.value)
    assert "https://" not in str(error.value)


@pytest.mark.parametrize("raw", [{}, {"ok": "yes", "result": {}}, {"ok": True}])
def test_malformed_api_response_is_rejected(raw):
    from dota_dungeon.telegram.client import BotAPIError, BotClient
    with pytest.raises(BotAPIError):
        BotClient("dummy", transport=lambda *args: raw, attempts=1).call("getMe", {})
